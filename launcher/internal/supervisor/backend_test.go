package supervisor

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"neo-tts/launcher/internal/config"
	winplatform "neo-tts/launcher/internal/platform/windows"
	"neo-tts/launcher/internal/state"
)

func TestOwnedBackendStartsProcessAndWaitsForHealth(t *testing.T) {
	projectRoot := t.TempDir()
	writeExecutableFile(t, filepath.Join(projectRoot, ".venv", "Scripts", "python.exe"))

	cfg := newBackendConfig(projectRoot, "dev", "owned")

	var (
		startCalls int
		waitCalls  int
		gotSpec    winplatform.ProcessSpec
	)

	result, err := EnsureBackend(context.Background(), cfg, state.RuntimeState{}, BackendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			startCalls++
			gotSpec = spec
			return ProcessHandle{PID: 24680}, nil
		},
		WaitForHealthy: func(ctx context.Context, url string, interval time.Duration) error {
			waitCalls++
			if waitCalls == 1 {
				return errors.New("not ready")
			}
			if url != "http://127.0.0.1:18600/health" {
				t.Fatalf("WaitForHealthy url = %q, want http://127.0.0.1:18600/health", url)
			}
			return nil
		},
	})
	if err != nil {
		t.Fatalf("EnsureBackend returned error: %v", err)
	}

	if startCalls != 1 {
		t.Fatalf("StartProcess calls = %d, want 1", startCalls)
	}
	if waitCalls != 2 {
		t.Fatalf("WaitForHealthy calls = %d, want 2", waitCalls)
	}
	if gotSpec.WorkingDirectory != projectRoot {
		t.Fatalf("WorkingDirectory = %q, want %q", gotSpec.WorkingDirectory, projectRoot)
	}
	if gotSpec.WindowStyle != winplatform.WindowInheritConsole {
		t.Fatalf("WindowStyle = %q, want inherit-console", gotSpec.WindowStyle)
	}
	if !gotSpec.AttachStdIO {
		t.Fatal("AttachStdIO = false, want true")
	}
	if !strings.Contains(gotSpec.Command, filepath.Join(projectRoot, ".venv", "Scripts", "python.exe")) {
		t.Fatalf("Command = %q, want venv python path", gotSpec.Command)
	}
	if !strings.Contains(gotSpec.Command, "-m backend.app.cli --host 127.0.0.1 --port 18600") {
		t.Fatalf("Command = %q, want backend cli args", gotSpec.Command)
	}
	if result.State.Backend.PID != 24680 {
		t.Fatalf("Backend PID = %d, want 24680", result.State.Backend.PID)
	}
	if result.State.Backend.Mode != "owned" {
		t.Fatalf("Backend Mode = %q, want owned", result.State.Backend.Mode)
	}
}

func TestExternalBackendOnlyChecksHealth(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := newBackendConfig(projectRoot, "dev", "external")
	cfg.Backend.ExternalOrigin = "http://127.0.0.1:19600"

	waitCalls := 0
	result, err := EnsureBackend(context.Background(), cfg, state.RuntimeState{}, BackendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			t.Fatalf("StartProcess should not be called for external backend")
			return ProcessHandle{}, nil
		},
		WaitForHealthy: func(ctx context.Context, url string, interval time.Duration) error {
			waitCalls++
			if url != "http://127.0.0.1:19600/health" {
				t.Fatalf("WaitForHealthy url = %q, want http://127.0.0.1:19600/health", url)
			}
			return nil
		},
	})
	if err != nil {
		t.Fatalf("EnsureBackend returned error: %v", err)
	}

	if waitCalls != 1 {
		t.Fatalf("WaitForHealthy calls = %d, want 1", waitCalls)
	}
	if result.State.Backend.Mode != "external" {
		t.Fatalf("Backend Mode = %q, want external", result.State.Backend.Mode)
	}
	if result.State.Backend.PID != 0 {
		t.Fatalf("Backend PID = %d, want 0", result.State.Backend.PID)
	}
}

func TestBackendUnknownPortOccupantFailsWithoutKill(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := newBackendConfig(projectRoot, "dev", "owned")

	var (
		startCalls int
		killCalls  int
	)

	_, err := EnsureBackend(context.Background(), cfg, state.RuntimeState{}, BackendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			startCalls++
			return ProcessHandle{}, nil
		},
		WaitForHealthy: func(ctx context.Context, url string, interval time.Duration) error {
			return nil
		},
		KillProcess: func(pid int) error {
			killCalls++
			return nil
		},
	})
	if !errors.Is(err, ErrPortOccupied) {
		t.Fatalf("EnsureBackend error = %v, want ErrPortOccupied", err)
	}
	if startCalls != 0 {
		t.Fatalf("StartProcess calls = %d, want 0", startCalls)
	}
	if killCalls != 0 {
		t.Fatalf("KillProcess calls = %d, want 0", killCalls)
	}
}

func TestBackendOwnedCleanupResidualsThenKillsPreviousProcess(t *testing.T) {
	projectRoot := t.TempDir()
	writeExecutableFile(t, filepath.Join(projectRoot, ".venv", "Scripts", "python.exe"))

	cfg := newBackendConfig(projectRoot, "dev", "owned")
	previous := state.RuntimeState{
		Backend: state.BackendState{
			Mode:   "owned",
			PID:    1357,
			Origin: "http://127.0.0.1:18600",
		},
	}

	var (
		waitCalls    int
		cleanupCalls int
		killCalls    int
		oldAlive     = true
	)

	_, err := EnsureBackend(context.Background(), cfg, previous, BackendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			return ProcessHandle{PID: 2468}, nil
		},
		WaitForHealthy: func(ctx context.Context, url string, interval time.Duration) error {
			waitCalls++
			switch waitCalls {
			case 1:
				return nil
			case 2:
				return errors.New("port released")
			default:
				return nil
			}
		},
		CleanupResiduals: func(ctx context.Context, url string) error {
			cleanupCalls++
			if url != "http://127.0.0.1:18600/v1/audio/inference/cleanup-residuals" {
				t.Fatalf("CleanupResiduals url = %q, want cleanup endpoint", url)
			}
			return nil
		},
		IsProcessRunning: func(pid int) bool {
			return pid == 1357 && oldAlive
		},
		KillProcess: func(pid int) error {
			killCalls++
			if pid != 1357 {
				t.Fatalf("KillProcess pid = %d, want 1357", pid)
			}
			oldAlive = false
			return nil
		},
	})
	if err != nil {
		t.Fatalf("EnsureBackend returned error: %v", err)
	}

	if cleanupCalls != 1 {
		t.Fatalf("CleanupResiduals calls = %d, want 1", cleanupCalls)
	}
	if killCalls != 1 {
		t.Fatalf("KillProcess calls = %d, want 1", killCalls)
	}
}

func TestBackendDevModePrefersProjectVenvPython(t *testing.T) {
	projectRoot := t.TempDir()
	writeExecutableFile(t, filepath.Join(projectRoot, ".venv", "Scripts", "python.exe"))

	cfg := newBackendConfig(projectRoot, "dev", "owned")

	got, err := resolvePythonExecutable(cfg)
	if err != nil {
		t.Fatalf("resolvePythonExecutable returned error: %v", err)
	}

	want := filepath.Join(projectRoot, ".venv", "Scripts", "python.exe")
	if got != want {
		t.Fatalf("resolvePythonExecutable = %q, want %q", got, want)
	}
}

func TestBackendProductModePrefersBundledRuntimePython(t *testing.T) {
	projectRoot := t.TempDir()
	writeExecutableFile(t, filepath.Join(projectRoot, "runtime", "python", "python.exe"))

	cfg := newBackendConfig(projectRoot, "product", "owned")

	got, err := resolvePythonExecutable(cfg)
	if err != nil {
		t.Fatalf("resolvePythonExecutable returned error: %v", err)
	}

	want := filepath.Join(projectRoot, "runtime", "python", "python.exe")
	if got != want {
		t.Fatalf("resolvePythonExecutable = %q, want %q", got, want)
	}
}

func TestBackendCrashMarksDegradedAndRequestsFrontendStop(t *testing.T) {
	stopCalls := 0

	result, err := HandleBackendLoss(state.RuntimeState{
		LastPhase: "running",
		Backend: state.BackendState{
			Mode: "owned",
			PID:  24680,
		},
	}, BackendLossDeps{
		StopFrontend: func() error {
			stopCalls++
			return nil
		},
	})
	if err != nil {
		t.Fatalf("HandleBackendLoss returned error: %v", err)
	}

	if stopCalls != 1 {
		t.Fatalf("StopFrontend calls = %d, want 1", stopCalls)
	}
	if result.LastPhase != "degraded" {
		t.Fatalf("LastPhase = %q, want degraded", result.LastPhase)
	}
	if !strings.Contains(result.LastError, "owned backend exited unexpectedly") {
		t.Fatalf("LastError = %q, want owned backend exited unexpectedly", result.LastError)
	}
}

func TestExternalBackendLossDoesNotAttemptTakeover(t *testing.T) {
	stopCalls := 0
	takeoverCalls := 0

	result, err := HandleBackendLoss(state.RuntimeState{
		LastPhase: "running",
		Backend: state.BackendState{
			Mode:   "external",
			Origin: "http://127.0.0.1:18600",
		},
	}, BackendLossDeps{
		StopFrontend: func() error {
			stopCalls++
			return nil
		},
		TakeoverBackend: func() error {
			takeoverCalls++
			return nil
		},
	})
	if err != nil {
		t.Fatalf("HandleBackendLoss returned error: %v", err)
	}

	if stopCalls != 1 {
		t.Fatalf("StopFrontend calls = %d, want 1", stopCalls)
	}
	if takeoverCalls != 0 {
		t.Fatalf("TakeoverBackend calls = %d, want 0", takeoverCalls)
	}
	if result.LastPhase != "degraded" {
		t.Fatalf("LastPhase = %q, want degraded", result.LastPhase)
	}
	if !strings.Contains(result.LastError, "external backend became unavailable") {
		t.Fatalf("LastError = %q, want external backend became unavailable", result.LastError)
	}
}

func newBackendConfig(projectRoot string, runtimeMode string, backendMode string) config.Config {
	return config.Config{
		ProjectRoot:  projectRoot,
		RuntimeMode:  runtimeMode,
		FrontendMode: "web",
		Backend: config.BackendConfig{
			Mode:          backendMode,
			Host:          "127.0.0.1",
			Port:          18600,
			DevPython:     filepath.Join(".venv", "Scripts", "python.exe"),
			ProductPython: filepath.Join("runtime", "python", "python.exe"),
		},
	}
}

func writeExecutableFile(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("MkdirAll(%q): %v", path, err)
	}
	if err := os.WriteFile(path, []byte("stub"), 0o644); err != nil {
		t.Fatalf("WriteFile(%q): %v", path, err)
	}
}
