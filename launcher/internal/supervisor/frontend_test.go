package supervisor

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
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
	asyncCalls := 0

	result, err := StartFrontendHost(context.Background(), cfg, current, FrontendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			gotSpec = spec
			return ProcessHandle{PID: 97531}, nil
		},
		RunAsync: func(task func()) {
			asyncCalls++
			task()
		},
		WaitForReady: func(ctx context.Context, url string, interval time.Duration) error {
			if url != "http://localhost:5175/" {
				t.Fatalf("WaitForReady url = %q, want http://localhost:5175/", url)
			}
			return nil
		},
		OpenBrowser: func(url string) error {
			openCalls++
			if url != "http://localhost:5175" {
				t.Fatalf("OpenBrowser url = %q, want http://localhost:5175", url)
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
	if gotSpec.Environment["VITE_LAUNCHER_OPEN_BROWSER"] != "" {
		t.Fatalf("VITE_LAUNCHER_OPEN_BROWSER = %q, want empty", gotSpec.Environment["VITE_LAUNCHER_OPEN_BROWSER"])
	}
	if asyncCalls != 1 {
		t.Fatalf("RunAsync calls = %d, want 1", asyncCalls)
	}
	if openCalls != 1 {
		t.Fatalf("OpenBrowser calls = %d, want 1 in dev mode", openCalls)
	}
	if result.State.FrontendHost.PID != 97531 {
		t.Fatalf("FrontendHost PID = %d, want 97531", result.State.FrontendHost.PID)
	}
	if result.State.FrontendHost.Kind != "vite" {
		t.Fatalf("FrontendHost Kind = %q, want vite", result.State.FrontendHost.Kind)
	}
	if !result.State.FrontendHost.BrowserOpened {
		t.Fatal("BrowserOpened = false, want true")
	}
}

func TestFrontendDevWebSchedulesBrowserOpenWithoutBlockingStartup(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := newFrontendConfig(projectRoot)
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode:   "owned",
			Port:   18600,
			Origin: "http://127.0.0.1:18600",
		},
	}

	order := make([]string, 0, 2)
	var scheduled func()

	result, err := StartFrontendHost(context.Background(), cfg, current, FrontendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			return ProcessHandle{PID: 97531}, nil
		},
		RunAsync: func(task func()) {
			scheduled = task
		},
		WaitForReady: func(ctx context.Context, url string, interval time.Duration) error {
			if url != "http://localhost:5175/" {
				t.Fatalf("WaitForReady url = %q, want http://localhost:5175/", url)
			}
			order = append(order, "wait")
			return nil
		},
		OpenBrowser: func(url string) error {
			if url != "http://localhost:5175" {
				t.Fatalf("OpenBrowser url = %q, want http://localhost:5175", url)
			}
			order = append(order, "open")
			return nil
		},
	})
	if err != nil {
		t.Fatalf("StartFrontendHost returned error: %v", err)
	}
	if scheduled == nil {
		t.Fatal("scheduled task = nil, want async browser open task")
	}
	if result.State.LastPhase != "running" {
		t.Fatalf("LastPhase = %q, want running", result.State.LastPhase)
	}
	if !result.State.FrontendHost.BrowserOpened {
		t.Fatal("BrowserOpened = false, want true")
	}
	if len(order) != 0 {
		t.Fatalf("order before scheduled run = %+v, want no wait/open before return", order)
	}

	scheduled()

	if len(order) != 2 || order[0] != "wait" || order[1] != "open" {
		t.Fatalf("order = %+v, want wait then open", order)
	}
}

func TestFrontendDevWebStillOpensBrowserWhenReadyProbeFails(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := newFrontendConfig(projectRoot)
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode:   "owned",
			Port:   18600,
			Origin: "http://127.0.0.1:18600",
		},
	}

	openCalls := 0
	result, err := StartFrontendHost(context.Background(), cfg, current, FrontendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			return ProcessHandle{PID: 97531}, nil
		},
		RunAsync: func(task func()) {
			task()
		},
		WaitForReady: func(ctx context.Context, url string, interval time.Duration) error {
			if url != "http://localhost:5175/" {
				t.Fatalf("WaitForReady url = %q, want http://localhost:5175/", url)
			}
			return errors.New("probe timed out")
		},
		OpenBrowser: func(url string) error {
			if url != "http://localhost:5175" {
				t.Fatalf("OpenBrowser url = %q, want http://localhost:5175", url)
			}
			openCalls++
			return nil
		},
	})
	if err != nil {
		t.Fatalf("StartFrontendHost returned error: %v", err)
	}
	if result.State.LastPhase != "running" {
		t.Fatalf("LastPhase = %q, want running", result.State.LastPhase)
	}
	if openCalls != 1 {
		t.Fatalf("OpenBrowser calls = %d, want 1", openCalls)
	}
}

func TestFrontendDevWebLogsReadyWaitAndBrowserOpen(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := newFrontendConfig(projectRoot)
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode:   "owned",
			Port:   18600,
			Origin: "http://127.0.0.1:18600",
		},
	}

	logs := make([]string, 0, 4)
	_, err := StartFrontendHost(context.Background(), cfg, current, FrontendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			return ProcessHandle{PID: 97531}, nil
		},
		RunAsync: func(task func()) {
			task()
		},
		WaitForReady: func(ctx context.Context, url string, interval time.Duration) error {
			return nil
		},
		Log: func(line string) {
			logs = append(logs, line)
		},
		OpenBrowser: func(url string) error {
			return nil
		},
	})
	if err != nil {
		t.Fatalf("StartFrontendHost returned error: %v", err)
	}

	if len(logs) != 4 {
		t.Fatalf("log count = %d, want 4; logs=%+v", len(logs), logs)
	}
	if logs[0] != "frontend browser wait begin probe_url=http://localhost:5175/ open_url=http://localhost:5175" {
		t.Fatalf("logs[0] = %q, want wait begin", logs[0])
	}
	if !strings.HasPrefix(logs[1], "frontend browser wait ready probe_url=http://localhost:5175/ elapsed_ms=") {
		t.Fatalf("logs[1] = %q, want wait ready", logs[1])
	}
	if logs[2] != "frontend browser open begin url=http://localhost:5175" {
		t.Fatalf("logs[2] = %q, want open begin", logs[2])
	}
	if !strings.HasPrefix(logs[3], "frontend browser open dispatched url=http://localhost:5175 elapsed_ms=") {
		t.Fatalf("logs[3] = %q, want open dispatched", logs[3])
	}
}

func TestFrontendDevWebLogsReadyFallbackBeforeBrowserOpen(t *testing.T) {
	projectRoot := t.TempDir()
	cfg := newFrontendConfig(projectRoot)
	current := state.RuntimeState{
		Backend: state.BackendState{
			Mode:   "owned",
			Port:   18600,
			Origin: "http://127.0.0.1:18600",
		},
	}

	logs := make([]string, 0, 4)
	_, err := StartFrontendHost(context.Background(), cfg, current, FrontendDeps{
		StartProcess: func(spec winplatform.ProcessSpec) (ProcessHandle, error) {
			return ProcessHandle{PID: 97531}, nil
		},
		RunAsync: func(task func()) {
			task()
		},
		WaitForReady: func(ctx context.Context, url string, interval time.Duration) error {
			return errors.New("probe timed out")
		},
		Log: func(line string) {
			logs = append(logs, line)
		},
		OpenBrowser: func(url string) error {
			return nil
		},
	})
	if err != nil {
		t.Fatalf("StartFrontendHost returned error: %v", err)
	}

	if len(logs) != 4 {
		t.Fatalf("log count = %d, want 4; logs=%+v", len(logs), logs)
	}
	if logs[0] != "frontend browser wait begin probe_url=http://localhost:5175/ open_url=http://localhost:5175" {
		t.Fatalf("logs[0] = %q, want wait begin", logs[0])
	}
	if !strings.HasPrefix(logs[1], "frontend browser wait fallback probe_url=http://localhost:5175/ elapsed_ms=") {
		t.Fatalf("logs[1] = %q, want wait fallback", logs[1])
	}
	if !strings.Contains(logs[1], "err=probe timed out") {
		t.Fatalf("logs[1] = %q, want probe error", logs[1])
	}
	if logs[2] != "frontend browser open begin url=http://localhost:5175" {
		t.Fatalf("logs[2] = %q, want open begin", logs[2])
	}
	if !strings.HasPrefix(logs[3], "frontend browser open dispatched url=http://localhost:5175 elapsed_ms=") {
		t.Fatalf("logs[3] = %q, want open dispatched", logs[3])
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
		RunAsync: func(task func()) {
			t.Fatal("RunAsync should not be called when browser already opened")
		},
		WaitForReady: func(ctx context.Context, url string, interval time.Duration) error {
			t.Fatal("WaitForReady should not be called when browser already opened")
			return nil
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

func TestFrontendStopUsesGracefulHookBeforeKill(t *testing.T) {
	current := state.RuntimeState{
		FrontendHost: state.FrontendHostState{
			Kind: "electron",
			PID:  2002,
		},
	}
	order := make([]string, 0, 2)

	err := stopFrontendHost(&current, FrontendStopDeps{
		GracefulStop: func(ctx context.Context) error {
			order = append(order, "graceful")
			return nil
		},
		IsProcessRunning: func(pid int) bool {
			return true
		},
		KillProcess: func(pid int) error {
			order = append(order, "kill")
			return nil
		},
	})
	if err != nil {
		t.Fatalf("stopFrontendHost returned error: %v", err)
	}

	if len(order) != 2 || order[0] != "graceful" || order[1] != "kill" {
		t.Fatalf("order = %+v, want graceful then kill", order)
	}
}

func TestFrontendStopContractTreatsElectronAsGracefulFirst(t *testing.T) {
	current := state.RuntimeState{
		FrontendHost: state.FrontendHostState{
			Kind: "electron",
			PID:  2002,
		},
	}
	order := make([]string, 0, 2)

	err := stopFrontendHost(&current, FrontendStopDeps{
		GracefulStop: func(ctx context.Context) error {
			order = append(order, "graceful")
			return nil
		},
		IsProcessRunning: func(pid int) bool {
			return false
		},
		KillProcess: func(pid int) error {
			order = append(order, "kill")
			return errors.New("kill should not be called")
		},
	})
	if err != nil {
		t.Fatalf("stopFrontendHost returned error: %v", err)
	}

	if len(order) != 1 || order[0] != "graceful" {
		t.Fatalf("order = %+v, want graceful only", order)
	}
}

func TestFrontendStopIgnoresKillErrorWhenTrackedPidAlreadyExited(t *testing.T) {
	current := state.RuntimeState{
		FrontendHost: state.FrontendHostState{
			Kind: "vite",
			PID:  2002,
		},
	}
	checks := 0

	err := stopFrontendHost(&current, FrontendStopDeps{
		IsProcessRunning: func(pid int) bool {
			checks++
			return checks == 1
		},
		KillProcess: func(pid int) error {
			return errors.New("process already exited")
		},
	})
	if err != nil {
		t.Fatalf("stopFrontendHost returned error: %v", err)
	}
	if current.FrontendHost.PID != 0 {
		t.Fatalf("FrontendHost.PID = %d, want 0", current.FrontendHost.PID)
	}
}

func TestWaitForFrontendReadyAcceptsTCPListenerBeforeHTTPReady(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("Listen returned error: %v", err)
	}
	defer listener.Close()

	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			_ = conn.Close()
		}
	}()

	waitCtx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()

	url := "http://" + listener.Addr().String() + "/"
	if err := waitForFrontendReady(waitCtx, url, 20*time.Millisecond); err != nil {
		t.Fatalf("waitForFrontendReady returned error: %v", err)
	}

	_ = listener.Close()
	<-done
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
