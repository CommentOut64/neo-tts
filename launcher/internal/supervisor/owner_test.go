package supervisor

import (
	"context"
	"errors"
	"testing"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/state"
)

func TestOwnerShutdownFromControlRequestStopsFrontendThenBackend(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	var (
		killedPIDs  []int
		savedStates []state.RuntimeState
	)

	done := make(chan error, 1)
	go func() {
		done <- RunOwner(ctx, newOwnerConfig(), state.RuntimeState{
			RuntimeMode: "dev",
			Backend: state.BackendState{
				Mode: "owned",
				PID:  1001,
			},
			FrontendHost: state.FrontendHostState{
				Kind:          "vite",
				PID:           2002,
				Port:          5175,
				Origin:        "http://localhost:5175",
				Command:       "npm run dev",
				BrowserOpened: true,
			},
			LastPhase: "running",
		}, OwnerDeps{
			IsProcessRunning: func(pid int) bool {
				return true
			},
			KillProcess: func(pid int) error {
				killedPIDs = append(killedPIDs, pid)
				return nil
			},
			FindPIDByPort: func(port int) (int, error) {
				return 0, nil
			},
			SaveState: func(current state.RuntimeState) error {
				savedStates = append(savedStates, current)
				return nil
			},
			Log: func(line string) {},
		})
	}()

	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("RunOwner returned error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("RunOwner did not stop after shutdown")
	}

	if len(killedPIDs) != 2 || killedPIDs[0] != 2002 || killedPIDs[1] != 1001 {
		t.Fatalf("killedPIDs = %+v, want frontend then backend", killedPIDs)
	}
	if len(savedStates) == 0 {
		t.Fatal("SaveState was not called")
	}
	last := savedStates[len(savedStates)-1]
	if last.LastPhase != "stopped" {
		t.Fatalf("LastPhase = %q, want stopped", last.LastPhase)
	}
	if last.FrontendHost.BrowserOpened {
		t.Fatalf("BrowserOpened = %t, want false after shutdown", last.FrontendHost.BrowserOpened)
	}
}

func TestOwnerMarksDegradedWhenBackendExits(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	backendExit := make(chan error, 1)
	degradedSaved := make(chan struct{}, 1)

	var (
		killedPIDs  []int
		savedStates []state.RuntimeState
	)

	done := make(chan error, 1)
	go func() {
		done <- RunOwner(ctx, newOwnerConfig(), state.RuntimeState{
			RuntimeMode: "dev",
			Backend: state.BackendState{
				Mode: "owned",
				PID:  1001,
			},
			FrontendHost: state.FrontendHostState{
				Kind:    "vite",
				PID:     2002,
				Port:    5175,
				Origin:  "http://localhost:5175",
				Command: "npm run dev",
			},
			LastPhase: "running",
		}, OwnerDeps{
			BackendExit: backendExit,
			IsProcessRunning: func(pid int) bool {
				return pid != 1001
			},
			KillProcess: func(pid int) error {
				killedPIDs = append(killedPIDs, pid)
				return nil
			},
			FindPIDByPort: func(port int) (int, error) {
				return 0, nil
			},
			SaveState: func(current state.RuntimeState) error {
				savedStates = append(savedStates, current)
				if current.LastPhase == "degraded" {
					select {
					case degradedSaved <- struct{}{}:
					default:
					}
				}
				return nil
			},
			Log: func(line string) {},
		})
	}()

	backendExit <- errors.New("exit status 1")

	select {
	case <-degradedSaved:
	case <-time.After(time.Second):
		t.Fatal("degraded state was not saved after backend exit")
	}
	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("RunOwner returned error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("RunOwner did not stop after cancel")
	}

	if len(killedPIDs) == 0 || killedPIDs[0] != 2002 {
		t.Fatalf("killedPIDs = %+v, want frontend pid 2002 stopped after backend exit", killedPIDs)
	}
	foundDegraded := false
	for _, item := range savedStates {
		if item.LastPhase == "degraded" {
			foundDegraded = true
			if item.LastError == "" {
				t.Fatal("degraded state LastError is empty")
			}
			break
		}
	}
	if !foundDegraded {
		t.Fatalf("savedStates = %+v, want degraded state", savedStates)
	}
}

func TestOwnerRestartsViteWithinRetryBudget(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	frontendExit := make(chan error, 1)
	restarted := make(chan struct{}, 1)

	var (
		savedStates []state.RuntimeState
		slept       time.Duration
		startCalls  int
	)

	done := make(chan error, 1)
	go func() {
		done <- RunOwner(ctx, newOwnerConfig(), state.RuntimeState{
			RuntimeMode: "dev",
			Backend: state.BackendState{
				Mode:   "owned",
				PID:    1001,
				Origin: "http://127.0.0.1:18600",
			},
			FrontendHost: state.FrontendHostState{
				Kind:   "vite",
				PID:    2002,
				Port:   5175,
				Origin: "http://localhost:5175",
			},
			LastPhase: "running",
		}, OwnerDeps{
			FrontendExit: frontendExit,
			Now: func() time.Time {
				return time.Date(2026, 4, 12, 12, 0, 0, 0, time.Local)
			},
			Sleep: func(delay time.Duration) {
				slept = delay
			},
			StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (FrontendResult, error) {
				startCalls++
				select {
				case restarted <- struct{}{}:
				default:
				}
				return FrontendResult{
					State: state.RuntimeState{
						FrontendHost: state.FrontendHostState{
							Kind:          "vite",
							PID:           3003,
							Port:          5175,
							Origin:        "http://localhost:5175",
							Command:       "npm run dev",
							BrowserOpened: true,
						},
						LastPhase: "running",
					},
					Exit: make(chan error, 1),
				}, nil
			},
			SaveState: func(current state.RuntimeState) error {
				savedStates = append(savedStates, current)
				return nil
			},
			Log: func(line string) {},
		})
	}()

	frontendExit <- errors.New("exit status 1")

	select {
	case <-restarted:
	case <-time.After(time.Second):
		t.Fatal("frontend was not restarted after exit")
	}
	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("RunOwner returned error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("RunOwner did not stop after cancel")
	}

	if slept != 5*time.Second {
		t.Fatalf("Sleep = %s, want 5s", slept)
	}
	if startCalls != 1 {
		t.Fatalf("StartFrontend calls = %d, want 1", startCalls)
	}
	var (
		restartingFound bool
		runningFound    bool
	)
	for _, item := range savedStates {
		if item.LastPhase == "frontend-restarting" {
			restartingFound = true
		}
		if item.LastPhase == "running" && item.FrontendHost.PID == 3003 {
			runningFound = true
		}
	}
	if !restartingFound {
		t.Fatalf("savedStates = %+v, want frontend-restarting state", savedStates)
	}
	if !runningFound {
		t.Fatalf("savedStates = %+v, want restarted running state", savedStates)
	}
}

func newOwnerConfig() config.Config {
	return config.Config{
		ProjectRoot:  `F:\neo-tts`,
		RuntimeMode:  "dev",
		FrontendMode: "web",
		Backend: config.BackendConfig{
			Mode: "owned",
			Host: "127.0.0.1",
			Port: 18600,
		},
	}
}
