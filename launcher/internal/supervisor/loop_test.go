package supervisor

import (
	"context"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/control"
	"neo-tts/launcher/internal/state"
	"neo-tts/launcher/internal/web"
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
			FindPIDByPort: func(port int) (int, error) {
				if port != 5175 {
					t.Fatalf("port = %d, want 5175", port)
				}
				return 0, nil
			},
			SaveState: func(current state.RuntimeState) error {
				savedStates = append(savedStates, current)
				return nil
			},
			ReadExitRequest: func() (*control.ExitRequest, error) {
				return nil, nil
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
			ReadExitRequest: func() (*control.ExitRequest, error) {
				return nil, nil
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
		ReadExitRequest: func() (*control.ExitRequest, error) {
			return nil, nil
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

func TestRunLoopShutdownClearsBrowserOpenedForNextLauncherStart(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	var savedStates []state.RuntimeState

	err := RunLoop(ctx, newLoopConfig(), state.RuntimeState{
		Backend: state.BackendState{
			Mode: "owned",
			PID:  1001,
		},
		FrontendHost: state.FrontendHostState{
			Kind:          "vite",
			PID:           2002,
			Port:          5175,
			Origin:        "http://127.0.0.1:5175",
			Command:       "npm run dev",
			BrowserOpened: true,
		},
		LastPhase: "running",
	}, LoopDeps{
		IsProcessRunning: func(pid int) bool {
			return true
		},
		KillProcess: func(pid int) error {
			return nil
		},
		FindPIDByPort: func(port int) (int, error) {
			return 0, nil
		},
		SaveState: func(current state.RuntimeState) error {
			savedStates = append(savedStates, current)
			return nil
		},
		ReadExitRequest: func() (*control.ExitRequest, error) {
			return nil, nil
		},
	})
	if err != nil {
		t.Fatalf("RunLoop returned error: %v", err)
	}
	if len(savedStates) == 0 {
		t.Fatal("SaveState was not called")
	}
	last := savedStates[len(savedStates)-1]
	if last.LastPhase != "stopped" {
		t.Fatalf("LastPhase = %q, want stopped", last.LastPhase)
	}
	if last.FrontendHost.BrowserOpened {
		t.Fatalf("BrowserOpened = %t, want false after full shutdown", last.FrontendHost.BrowserOpened)
	}
}

func TestRunLoopStopsWhenExitRequestAppears(t *testing.T) {
	ticks := make(chan time.Time, 1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	var (
		killedPIDs       []int
		savedStates      []state.RuntimeState
		exitRequestReads int
		deleteCalls      int
		startCalls       int
		findPortCalls    []int
	)

	done := make(chan error, 1)
	go func() {
		done <- RunLoop(ctx, newLoopConfig(), state.RuntimeState{
			LauncherPID: 4321,
			RuntimeMode: "dev",
			Backend: state.BackendState{
				Mode: "owned",
				PID:  1001,
			},
			FrontendHost: state.FrontendHostState{
				Kind: "vite",
				PID:  2002,
				Port: 5175,
			},
			LastPhase: "running",
		}, LoopDeps{
			Tick: ticks,
			IsProcessRunning: func(pid int) bool {
				return true
			},
			KillProcess: func(pid int) error {
				killedPIDs = append(killedPIDs, pid)
				return nil
			},
			FindPIDByPort: func(port int) (int, error) {
				findPortCalls = append(findPortCalls, port)
				return 0, nil
			},
			SaveState: func(current state.RuntimeState) error {
				savedStates = append(savedStates, current)
				return nil
			},
			ReadExitRequest: func() (*control.ExitRequest, error) {
				exitRequestReads++
				return &control.ExitRequest{
					Kind:        "user_exit",
					Source:      "frontend",
					RequestedAt: "2026-04-11T22:00:00+08:00",
					LauncherPID: 4321,
				}, nil
			},
			DeleteExitRequest: func() error {
				deleteCalls++
				return nil
			},
			StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (FrontendResult, error) {
				startCalls++
				return FrontendResult{}, nil
			},
			Log: func(line string) {},
		})
	}()

	ticks <- time.Now()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("RunLoop returned error: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("RunLoop did not stop after exit request")
	}

	if exitRequestReads == 0 {
		t.Fatal("ReadExitRequest was not called")
	}
	if deleteCalls != 1 {
		t.Fatalf("DeleteExitRequest calls = %d, want 1", deleteCalls)
	}
	if startCalls != 0 {
		t.Fatalf("StartFrontend calls = %d, want 0", startCalls)
	}
	if len(findPortCalls) != 1 || findPortCalls[0] != 5175 {
		t.Fatalf("FindPIDByPort calls = %+v, want [5175]", findPortCalls)
	}
	if len(killedPIDs) != 2 || killedPIDs[0] != 2002 || killedPIDs[1] != 1001 {
		t.Fatalf("killedPIDs = %+v, want frontend then backend", killedPIDs)
	}
	last := savedStates[len(savedStates)-1]
	if last.LastPhase != "stopped" {
		t.Fatalf("LastPhase = %q, want stopped", last.LastPhase)
	}
}

func TestExitRequestDoesNotTriggerFrontendCrashRestart(t *testing.T) {
	ticks := make(chan time.Time, 1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	var (
		startCalls  int
		deleteCalls int
	)

	done := make(chan error, 1)
	go func() {
		done <- RunLoop(ctx, newLoopConfig(), state.RuntimeState{
			LauncherPID: 9876,
			RuntimeMode: "dev",
			Backend: state.BackendState{
				Mode: "owned",
				PID:  1001,
			},
			FrontendHost: state.FrontendHostState{
				Kind: "vite",
				PID:  2002,
			},
			LastPhase: "running",
		}, LoopDeps{
			Tick: ticks,
			IsProcessRunning: func(pid int) bool {
				if pid == 2002 {
					return false
				}
				return true
			},
			KillProcess: func(pid int) error {
				return nil
			},
			SaveState: func(current state.RuntimeState) error {
				return nil
			},
			ReadExitRequest: func() (*control.ExitRequest, error) {
				return &control.ExitRequest{
					Kind:        "user_exit",
					Source:      "frontend",
					RequestedAt: "2026-04-11T22:00:00+08:00",
					LauncherPID: 9876,
				}, nil
			},
			DeleteExitRequest: func() error {
				deleteCalls++
				return nil
			},
			StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (FrontendResult, error) {
				startCalls++
				return FrontendResult{}, nil
			},
			Log: func(line string) {},
		})
	}()

	ticks <- time.Now()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("RunLoop returned error: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("RunLoop did not stop after exit request")
	}

	if startCalls != 0 {
		t.Fatalf("StartFrontend calls = %d, want 0", startCalls)
	}
	if deleteCalls != 1 {
		t.Fatalf("DeleteExitRequest calls = %d, want 1", deleteCalls)
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
	err := stopFrontendHost(&current, FrontendStopDeps{
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

func TestStepLoopIgnoresStaleExitRequestForDifferentLauncherPID(t *testing.T) {
	current := state.RuntimeState{
		LauncherPID: 9001,
		RuntimeMode: "dev",
		Backend: state.BackendState{
			Mode: "owned",
			PID:  1001,
		},
		FrontendHost: state.FrontendHostState{
			Kind: "vite",
			PID:  2002,
			Port: 5175,
		},
		LastPhase: "running",
	}

	deleteCalls := 0
	killCalls := 0
	next, crashTimes, err := stepLoop(context.Background(), newLoopConfig(), current, nil, LoopDeps{
		ReadExitRequest: func() (*control.ExitRequest, error) {
			return &control.ExitRequest{
				Kind:        "user_exit",
				Source:      "frontend",
				RequestedAt: "2026-04-11T23:40:00+08:00",
				LauncherPID: 12345,
			}, nil
		},
		DeleteExitRequest: func() error {
			deleteCalls++
			return nil
		},
		IsProcessRunning: func(pid int) bool {
			return true
		},
		KillProcess: func(pid int) error {
			killCalls++
			return nil
		},
		SaveState: func(current state.RuntimeState) error {
			return nil
		},
		Log: func(line string) {},
	})
	if err != nil {
		t.Fatalf("stepLoop returned error: %v", err)
	}
	if next != current {
		t.Fatalf("next = %+v, want unchanged current %+v", next, current)
	}
	if len(crashTimes) != 0 {
		t.Fatalf("crashTimes = %+v, want empty", crashTimes)
	}
	if deleteCalls != 1 {
		t.Fatalf("DeleteExitRequest calls = %d, want 1", deleteCalls)
	}
	if killCalls != 0 {
		t.Fatalf("KillProcess calls = %d, want 0", killCalls)
	}
}

func TestHandleShutdownStopsStaticServerBeforeClearingState(t *testing.T) {
	projectRoot := t.TempDir()
	distDir := filepath.Join(projectRoot, "frontend", "dist")
	if err := os.MkdirAll(distDir, 0o755); err != nil {
		t.Fatalf("MkdirAll(%q): %v", distDir, err)
	}
	if err := os.WriteFile(filepath.Join(distDir, "index.html"), []byte("<html>ok</html>"), 0o644); err != nil {
		t.Fatalf("WriteFile(index.html): %v", err)
	}

	server, err := web.StartStaticServer(web.Config{
		Host:    "127.0.0.1",
		Port:    0,
		DistDir: distDir,
	})
	if err != nil {
		t.Fatalf("StartStaticServer returned error: %v", err)
	}

	var savedStates []state.RuntimeState
	current := state.RuntimeState{
		LauncherPID: 9876,
		FrontendHost: state.FrontendHostState{
			Kind:   "static-server",
			Port:   server.Port,
			Origin: server.Origin,
		},
		LastPhase: "running",
	}

	err = handleShutdown(current, LoopDeps{
		SaveState: func(next state.RuntimeState) error {
			savedStates = append(savedStates, next)
			return nil
		},
		StaticServer: server,
		FindPIDByPort: func(port int) (int, error) {
			return 0, nil
		},
		Log: func(line string) {},
	})
	if err != nil {
		t.Fatalf("handleShutdown returned error: %v", err)
	}

	_, err = (&http.Client{Timeout: 200 * time.Millisecond}).Get(server.Origin + "/")
	if err == nil {
		t.Fatal("static server is still reachable after shutdown")
	}
	if len(savedStates) == 0 {
		t.Fatal("SaveState was not called")
	}
	last := savedStates[len(savedStates)-1]
	if last.FrontendHost.Kind != "" || last.FrontendHost.Port != 0 || last.FrontendHost.Origin != "" {
		t.Fatalf("FrontendHost = %+v, want cleared state", last.FrontendHost)
	}
}

func TestStopOwnedBackendIgnoresKillErrorWhenProcessAlreadyExited(t *testing.T) {
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode: "owned",
			PID:  1001,
		},
	}
	checks := 0

	err := stopOwnedBackend(&current, LoopDeps{
		IsProcessRunning: func(pid int) bool {
			checks++
			return checks == 1
		},
		KillProcess: func(pid int) error {
			return errors.New("process already exited")
		},
	})
	if err != nil {
		t.Fatalf("stopOwnedBackend returned error: %v", err)
	}
	if current.Backend.PID != 0 {
		t.Fatalf("Backend.PID = %d, want 0", current.Backend.PID)
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
