package supervisor

import (
	"context"
	"testing"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/state"
)

func TestRunLoopBackendCrashStopsFrontendAndMarksDegraded(t *testing.T) {
	ticks := make(chan time.Time, 1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	var (
		savedStates []state.RuntimeState
		killedPIDs  []int
		logs        []string
	)

	done := make(chan error, 1)
	go func() {
		done <- RunLoop(ctx, newLoopConfig(), state.RuntimeState{
			RuntimeMode:  "dev",
			FrontendMode: "web",
			Backend: state.BackendState{
				Mode: "owned",
				PID:  1001,
			},
			FrontendHost: state.FrontendHostState{
				PID: 2002,
			},
			LastPhase: "running",
		}, LoopDeps{
			Tick: ticks,
			IsProcessRunning: func(pid int) bool {
				return pid != 1001
			},
			KillProcess: func(pid int) error {
				killedPIDs = append(killedPIDs, pid)
				return nil
			},
			SaveState: func(current state.RuntimeState) error {
				savedStates = append(savedStates, current)
				return nil
			},
			Log: func(line string) {
				logs = append(logs, line)
			},
		})
	}()

	ticks <- time.Now()
	time.Sleep(50 * time.Millisecond)
	cancel()

	if err := <-done; err != nil {
		t.Fatalf("RunLoop returned error: %v", err)
	}
	if len(killedPIDs) == 0 || killedPIDs[0] != 2002 {
		t.Fatalf("killedPIDs = %+v, want frontend pid 2002 stopped first", killedPIDs)
	}
	if len(savedStates) == 0 {
		t.Fatal("SaveState was not called")
	}
	var degradedFound bool
	for _, item := range savedStates {
		if item.LastPhase == "degraded" {
			if item.LastError == "" {
				t.Fatal("degraded state LastError is empty")
			}
			degradedFound = true
			break
		}
	}
	if !degradedFound {
		t.Fatalf("savedStates = %+v, want one degraded state", savedStates)
	}
	if len(logs) == 0 {
		t.Fatal("logs is empty")
	}
}

func TestRunLoopFrontendCrashRestartsAfterDelay(t *testing.T) {
	ticks := make(chan time.Time, 1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	var (
		slept       time.Duration
		startCalls  int
		savedStates []state.RuntimeState
	)

	done := make(chan error, 1)
	go func() {
		done <- RunLoop(ctx, newLoopConfig(), state.RuntimeState{
			RuntimeMode:  "dev",
			FrontendMode: "web",
			Backend: state.BackendState{
				Mode:   "owned",
				PID:    1001,
				Origin: "http://127.0.0.1:18600",
			},
			FrontendHost: state.FrontendHostState{
				PID: 2002,
			},
			LastPhase: "running",
		}, LoopDeps{
			Tick: ticks,
			IsProcessRunning: func(pid int) bool {
				return pid == 1001
			},
			Now: func() time.Time {
				return time.Date(2026, 4, 10, 12, 0, 0, 0, time.Local)
			},
			Sleep: func(delay time.Duration) {
				slept = delay
			},
			StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (FrontendResult, error) {
				startCalls++
				return FrontendResult{
					State: state.RuntimeState{
						FrontendHost: state.FrontendHostState{
							PID:           3003,
							Kind:          "vite",
							Origin:        "http://127.0.0.1:5175",
							BrowserOpened: true,
						},
						LastPhase: "running",
					},
				}, nil
			},
			SaveState: func(current state.RuntimeState) error {
				savedStates = append(savedStates, current)
				return nil
			},
			KillProcess: func(pid int) error {
				return nil
			},
			Log: func(line string) {},
		})
	}()

	ticks <- time.Now()
	time.Sleep(50 * time.Millisecond)
	cancel()

	if err := <-done; err != nil {
		t.Fatalf("RunLoop returned error: %v", err)
	}
	if slept != 5*time.Second {
		t.Fatalf("Sleep = %s, want 5s", slept)
	}
	if startCalls != 1 {
		t.Fatalf("StartFrontend calls = %d, want 1", startCalls)
	}
	if len(savedStates) < 2 {
		t.Fatalf("SaveState calls = %d, want at least 2", len(savedStates))
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
		t.Fatalf("savedStates = %+v, want one frontend-restarting state", savedStates)
	}
	if !runningFound {
		t.Fatalf("savedStates = %+v, want one running state with pid 3003", savedStates)
	}
}

func TestRunLoopContextCancelStopsOwnedProcesses(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	var (
		killedPIDs  []int
		savedStates []state.RuntimeState
	)

	err := RunLoop(ctx, newLoopConfig(), state.RuntimeState{
		Backend: state.BackendState{
			Mode: "owned",
			PID:  1001,
		},
		FrontendHost: state.FrontendHostState{
			PID: 2002,
		},
		LastPhase: "running",
	}, LoopDeps{
		IsProcessRunning: func(pid int) bool {
			return true
		},
		KillProcess: func(pid int) error {
			killedPIDs = append(killedPIDs, pid)
			return nil
		},
		SaveState: func(current state.RuntimeState) error {
			savedStates = append(savedStates, current)
			return nil
		},
	})
	if err != nil {
		t.Fatalf("RunLoop returned error: %v", err)
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
}

func TestStopFrontendHostKillsPidAndPortOccupant(t *testing.T) {
	current := state.RuntimeState{
		FrontendHost: state.FrontendHostState{
			PID:  2002,
			Port: 5175,
		},
	}

	var killedPIDs []int
	err := stopFrontendHost(&current, LoopDeps{
		IsProcessRunning: func(pid int) bool {
			return pid == 2002
		},
		KillProcess: func(pid int) error {
			killedPIDs = append(killedPIDs, pid)
			return nil
		},
		FindPIDByPort: func(port int) (int, error) {
			if port != 5175 {
				t.Fatalf("port = %d, want 5175", port)
			}
			return 3003, nil
		},
	})
	if err != nil {
		t.Fatalf("stopFrontendHost returned error: %v", err)
	}

	if len(killedPIDs) != 2 || killedPIDs[0] != 2002 || killedPIDs[1] != 3003 {
		t.Fatalf("killedPIDs = %+v, want tracked pid then port pid", killedPIDs)
	}
	if current.FrontendHost.PID != 0 {
		t.Fatalf("FrontendHost.PID = %d, want 0", current.FrontendHost.PID)
	}
}

func newLoopConfig() config.Config {
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
