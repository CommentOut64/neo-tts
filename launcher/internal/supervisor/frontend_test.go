package supervisor

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"neo-tts/launcher/internal/config"
	winplatform "neo-tts/launcher/internal/platform/windows"
	"neo-tts/launcher/internal/state"
)

func TestFrontendDevWebStartsViteWithBackendOrigin(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := newFrontendConfig(projectRoot)
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode:   "owned",
			Port:   18600,
			Origin: "http://127.0.0.1:18600",
		},
	}

	var gotSpec winplatform.ProcessSpec
	openCalls := 0

	result, err := StartFrontendHost(context.Background(), cfg, current, FrontendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			gotSpec = spec
			return ProcessHandle{PID: 97531}, nil
		},
		OpenBrowser: func(url string) error {
			openCalls++
			if url != "http://127.0.0.1:5175" {
				t.Fatalf("OpenBrowser url = %q, want http://127.0.0.1:5175", url)
			}
			return nil
		},
	})
	if err != nil {
		t.Fatalf("StartFrontendHost returned error: %v", err)
	}

	if gotSpec.Command != "npm run dev" {
		t.Fatalf("Command = %q, want npm run dev", gotSpec.Command)
	}
	if gotSpec.WorkingDirectory != filepath.Join(projectRoot, "frontend") {
		t.Fatalf("WorkingDirectory = %q, want frontend dir", gotSpec.WorkingDirectory)
	}
	if gotSpec.WindowStyle != winplatform.WindowNewConsole {
		t.Fatalf("WindowStyle = %q, want new-console", gotSpec.WindowStyle)
	}
	if gotSpec.AttachStdIO {
		t.Fatal("AttachStdIO = true, want false")
	}
	if gotSpec.Environment["VITE_BACKEND_ORIGIN"] != "http://127.0.0.1:18600" {
		t.Fatalf("VITE_BACKEND_ORIGIN = %q, want http://127.0.0.1:18600", gotSpec.Environment["VITE_BACKEND_ORIGIN"])
	}
	if openCalls != 1 {
		t.Fatalf("OpenBrowser calls = %d, want 1", openCalls)
	}
	if result.State.FrontendHost.PID != 97531 {
		t.Fatalf("FrontendHost PID = %d, want 97531", result.State.FrontendHost.PID)
	}
	if result.State.FrontendHost.Kind != "vite" {
		t.Fatalf("FrontendHost Kind = %q, want vite", result.State.FrontendHost.Kind)
	}
}

func TestFrontendProductWebStartsStaticServer(t *testing.T) {
	projectRoot := t.TempDir()
	distDir := filepath.Join(projectRoot, "frontend", "dist")
	if err := os.MkdirAll(distDir, 0o755); err != nil {
		t.Fatalf("MkdirAll(%q): %v", distDir, err)
	}
	if err := os.WriteFile(filepath.Join(distDir, "index.html"), []byte("<html>ok</html>"), 0o644); err != nil {
		t.Fatalf("WriteFile(index.html): %v", err)
	}

	cfg := newFrontendConfig(projectRoot)
	cfg.RuntimeMode = "product"
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode:   "owned",
			Port:   18600,
			Origin: "http://127.0.0.1:18600",
		},
	}

	openCalls := 0
	result, err := StartFrontendHost(context.Background(), cfg, current, FrontendDeps{
		OpenBrowser: func(url string) error {
			openCalls++
			return nil
		},
	})
	if err != nil {
		t.Fatalf("StartFrontendHost returned error: %v", err)
	}
	defer func() {
		if result.StaticServer == nil {
			return
		}
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = result.StaticServer.Stop(shutdownCtx)
	}()

	if result.StaticServer == nil {
		t.Fatal("StaticServer = nil, want started server")
	}
	if result.State.FrontendHost.Kind != "static-server" {
		t.Fatalf("FrontendHost Kind = %q, want static-server", result.State.FrontendHost.Kind)
	}
	if openCalls != 1 {
		t.Fatalf("OpenBrowser calls = %d, want 1", openCalls)
	}
}

func TestFrontendRepeatedLaunchDoesNotReopenBrowser(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := newFrontendConfig(projectRoot)
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode:   "owned",
			Port:   18600,
			Origin: "http://127.0.0.1:18600",
		},
		FrontendHost: state.FrontendHostState{
			BrowserOpened: true,
		},
	}

	openCalls := 0

	result, err := StartFrontendHost(context.Background(), cfg, current, FrontendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			return ProcessHandle{PID: 86420}, nil
		},
		OpenBrowser: func(url string) error {
			openCalls++
			return nil
		},
	})
	if err != nil {
		t.Fatalf("StartFrontendHost returned error: %v", err)
	}

	if openCalls != 0 {
		t.Fatalf("OpenBrowser calls = %d, want 0", openCalls)
	}
	if !result.State.FrontendHost.BrowserOpened {
		t.Fatal("BrowserOpened = false, want true")
	}
}

func TestFrontendRestartAfterFiveSecondDelay(t *testing.T) {
	now := time.Date(2026, 4, 10, 12, 0, 0, 0, time.Local)
	var slept time.Duration

	result, err := HandleFrontendCrash(state.RuntimeState{}, nil, FrontendCrashDeps{
		Now: func() time.Time {
			return now
		},
		Sleep: func(delay time.Duration) {
			slept = delay
		},
	})
	if err != nil {
		t.Fatalf("HandleFrontendCrash returned error: %v", err)
	}

	if slept != 5*time.Second {
		t.Fatalf("Sleep duration = %s, want 5s", slept)
	}
	if !result.ShouldRestart {
		t.Fatal("ShouldRestart = false, want true")
	}
	if len(result.CrashTimes) != 1 {
		t.Fatalf("CrashTimes len = %d, want 1", len(result.CrashTimes))
	}
}

func TestFrontendStopsRetryingAfterThreeCrashesInSixtySeconds(t *testing.T) {
	now := time.Date(2026, 4, 10, 12, 0, 0, 0, time.Local)
	stopBackendCalls := 0

	result, err := HandleFrontendCrash(state.RuntimeState{}, []time.Time{
		now.Add(-50 * time.Second),
		now.Add(-10 * time.Second),
	}, FrontendCrashDeps{
		Now: func() time.Time {
			return now
		},
		Sleep: func(delay time.Duration) {},
		StopBackend: func() error {
			stopBackendCalls++
			return nil
		},
	})
	if err != nil {
		t.Fatalf("HandleFrontendCrash returned error: %v", err)
	}

	if result.ShouldRestart {
		t.Fatal("ShouldRestart = true, want false")
	}
	if stopBackendCalls != 1 {
		t.Fatalf("StopBackend calls = %d, want 1", stopBackendCalls)
	}
	if result.State.LastPhase != "degraded" {
		t.Fatalf("LastPhase = %q, want degraded", result.State.LastPhase)
	}
}

func newFrontendConfig(projectRoot string) config.Config {
	return config.Config{
		ProjectRoot:  projectRoot,
		RuntimeMode:  "dev",
		FrontendMode: "web",
		Backend: config.BackendConfig{
			Mode: "owned",
			Host: "127.0.0.1",
			Port: 18600,
		},
	}
}
