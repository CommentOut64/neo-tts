package state

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWriteRuntimeStateAtomically(t *testing.T) {
	projectRoot := t.TempDir()
	runtimeState := RuntimeState{
		LauncherPID:  12345,
		RuntimeMode:  "dev",
		FrontendMode: "web",
		LastPhase:    "running",
	}

	path, err := Save(projectRoot, runtimeState)
	if err != nil {
		t.Fatalf("Save returned error: %v", err)
	}

	if _, err := os.Stat(path); err != nil {
		t.Fatalf("Stat(%q): %v", path, err)
	}
	if _, err := os.Stat(path + ".tmp"); !os.IsNotExist(err) {
		t.Fatalf("temporary state file should not remain, got err=%v", err)
	}
}

func TestLoadRuntimeStateReturnsZeroValueWhenMissing(t *testing.T) {
	projectRoot := t.TempDir()

	runtimeState, err := Load(projectRoot)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if runtimeState.LauncherPID != 0 {
		t.Fatalf("LauncherPID = %d, want 0", runtimeState.LauncherPID)
	}
	if runtimeState.RuntimeMode != "" {
		t.Fatalf("RuntimeMode = %q, want empty", runtimeState.RuntimeMode)
	}
	if runtimeState.FrontendMode != "" {
		t.Fatalf("FrontendMode = %q, want empty", runtimeState.FrontendMode)
	}
}

func TestLoadRoundTripsSavedRuntimeState(t *testing.T) {
	projectRoot := t.TempDir()
	want := RuntimeState{
		LauncherPID:   12345,
		RuntimeMode:   "product",
		FrontendMode:  "web",
		StartupSource: "double-click",
		IsElevated:    true,
		LastPhase:     "booting",
		LogFilePath:   filepath.Join(projectRoot, "logs", "launcher", "launcher.log"),
		Backend: BackendState{
			Mode:    "owned",
			PID:     24680,
			Port:    18600,
			Origin:  "http://127.0.0.1:18600",
			Command: "python -m backend.app.cli --port 18600",
		},
		FrontendHost: FrontendHostState{
			Kind:          "vite",
			PID:           97531,
			Port:          5175,
			Origin:        "http://127.0.0.1:5175",
			Command:       "npm run dev",
			BrowserOpened: true,
		},
		LastError: "probe timeout",
	}

	if _, err := Save(projectRoot, want); err != nil {
		t.Fatalf("Save returned error: %v", err)
	}

	got, err := Load(projectRoot)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if got != want {
		t.Fatalf("Load returned %+v, want %+v", got, want)
	}
}
