package supervisor

import (
	"errors"
	"testing"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/state"
)

func TestHandleShutdownStopsOwnedProcessesAndClearsBrowserState(t *testing.T) {
	var (
		killedPIDs  []int
		savedStates []state.RuntimeState
	)

	err := handleShutdown(state.RuntimeState{
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
	}, withLifecycleDefaults(newLifecycleConfig(), state.RuntimeState{}, lifecycleDeps{
		IsProcessRunning: func(pid int) bool {
			return true
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
		Log: func(line string) {},
	}))
	if err != nil {
		t.Fatalf("handleShutdown returned error: %v", err)
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

func TestStopOwnedBackendIgnoresKillErrorWhenProcessAlreadyExited(t *testing.T) {
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode: "owned",
			PID:  1001,
		},
	}
	checks := 0

	err := stopOwnedBackend(&current, withLifecycleDefaults(newLifecycleConfig(), state.RuntimeState{}, lifecycleDeps{
		IsProcessRunning: func(pid int) bool {
			checks++
			return checks == 1
		},
		KillProcess: func(pid int) error {
			return errors.New("process already exited")
		},
	}))
	if err != nil {
		t.Fatalf("stopOwnedBackend returned error: %v", err)
	}
	if current.Backend.PID != 0 {
		t.Fatalf("Backend.PID = %d, want 0", current.Backend.PID)
	}
}

func newLifecycleConfig() config.Config {
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
