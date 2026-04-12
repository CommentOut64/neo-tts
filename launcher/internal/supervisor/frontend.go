package supervisor

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/url"
	"path/filepath"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/httpcheck"
	winplatform "neo-tts/launcher/internal/platform/windows"
	"neo-tts/launcher/internal/state"
	"neo-tts/launcher/internal/web"
)

const (
	frontendDevPort         = 5175
	frontendReadyInterval   = 250 * time.Millisecond
	frontendReadyTimeout    = 15 * time.Second
	frontendRestartDelay    = 5 * time.Second
	frontendCrashWindow     = 60 * time.Second
	frontendCrashRetryLimit = 3
)

type FrontendDeps struct {
	StartProcess func(spec winplatform.ProcessSpec) (ProcessHandle, error)
	RunAsync     func(task func())
	WaitForReady func(ctx context.Context, url string, interval time.Duration) error
	Log          func(line string)
	OpenBrowser  func(url string) error
}

type FrontendStopDeps struct {
	IsProcessRunning func(pid int) bool
	KillProcess      func(pid int) error
	FindPIDByPort    func(port int) (int, error)
	StaticServer     *web.StaticServer
	GracefulStop     func(ctx context.Context) error
}

type FrontendCrashDeps struct {
	Now         func() time.Time
	Sleep       func(delay time.Duration)
	StopBackend func() error
}

type FrontendResult struct {
	State        state.RuntimeState
	StaticServer *web.StaticServer
	GracefulStop func(ctx context.Context) error
}

type FrontendCrashResult struct {
	State         state.RuntimeState
	CrashTimes    []time.Time
	ShouldRestart bool
}

func StartFrontendHost(ctx context.Context, cfg config.Config, current state.RuntimeState, deps FrontendDeps) (FrontendResult, error) {
	deps = withFrontendDefaults(deps)
	if cfg.FrontendMode != "web" {
		return FrontendResult{}, errors.New("electron frontend host is not implemented yet")
	}
	if cfg.RuntimeMode == "product" {
		return startProductWebFrontend(current, deps, cfg)
	}
	if cfg.RuntimeMode != "dev" {
		return FrontendResult{}, fmt.Errorf("unsupported runtime mode: %s", cfg.RuntimeMode)
	}

	backendOrigin := current.Backend.Origin
	if backendOrigin == "" {
		backendOrigin = backendOriginFromConfig(cfg)
	}

	handle, err := deps.StartProcess(winplatform.ProcessSpec{
		Command:          "npm run dev",
		WorkingDirectory: filepath.Join(cfg.ProjectRoot, "frontend"),
		Environment: map[string]string{
			"VITE_BACKEND_ORIGIN": backendOrigin,
		},
		WindowStyle: winplatform.WindowNewConsole,
		AttachStdIO: false,
	})
	if err != nil {
		return FrontendResult{}, err
	}

	next := current
	next.RuntimeMode = cfg.RuntimeMode
	next.FrontendMode = cfg.FrontendMode
	next.FrontendHost = state.FrontendHostState{
		Kind:          "vite",
		PID:           handle.PID,
		Port:          frontendDevPort,
		Origin:        frontendDevURL(),
		Command:       "npm run dev",
		BrowserOpened: current.FrontendHost.BrowserOpened,
	}

	if !next.FrontendHost.BrowserOpened {
		next.FrontendHost.BrowserOpened = true
		scheduleBrowserOpen(next.FrontendHost.Origin, frontendReadyURL(next.FrontendHost.Origin), deps)
	}

	next.LastPhase = "running"
	return FrontendResult{State: next}, nil
}

func HandleFrontendCrash(current state.RuntimeState, crashTimes []time.Time, deps FrontendCrashDeps) (FrontendCrashResult, error) {
	deps = withFrontendCrashDefaults(deps)
	deps.Sleep(frontendRestartDelay)

	now := deps.Now()
	window := make([]time.Time, 0, len(crashTimes)+1)
	for _, item := range crashTimes {
		if now.Sub(item) <= frontendCrashWindow {
			window = append(window, item)
		}
	}
	window = append(window, now)

	next := current
	if len(window) >= frontendCrashRetryLimit {
		next.LastPhase = "degraded"
		next.LastError = "frontend host crashed too many times"
		if deps.StopBackend != nil {
			if err := deps.StopBackend(); err != nil {
				next.LastError = next.LastError + ": failed to stop backend: " + err.Error()
				return FrontendCrashResult{State: next, CrashTimes: window}, err
			}
		}
		return FrontendCrashResult{
			State:         next,
			CrashTimes:    window,
			ShouldRestart: false,
		}, nil
	}

	next.LastPhase = "frontend-restarting"
	next.LastError = "frontend host exited unexpectedly"
	return FrontendCrashResult{
		State:         next,
		CrashTimes:    window,
		ShouldRestart: true,
	}, nil
}

func startProductWebFrontend(current state.RuntimeState, deps FrontendDeps, cfg config.Config) (FrontendResult, error) {
	server, err := web.StartStaticServer(web.Config{
		Host:    "127.0.0.1",
		Port:    web.DefaultStaticServerPort,
		DistDir: filepath.Join(cfg.ProjectRoot, "frontend", "dist"),
	})
	if err != nil {
		return FrontendResult{}, err
	}

	next := current
	next.RuntimeMode = cfg.RuntimeMode
	next.FrontendMode = cfg.FrontendMode
	next.FrontendHost = state.FrontendHostState{
		Kind:          "static-server",
		Port:          server.Port,
		Origin:        server.Origin,
		Command:       "builtin static server",
		BrowserOpened: current.FrontendHost.BrowserOpened,
	}

	if !next.FrontendHost.BrowserOpened {
		if err := deps.OpenBrowser(next.FrontendHost.Origin); err != nil {
			_ = server.Stop(context.Background())
			return FrontendResult{}, err
		}
		next.FrontendHost.BrowserOpened = true
	}

	next.LastPhase = "running"
	return FrontendResult{
		State:        next,
		StaticServer: server,
	}, nil
}

func withFrontendDefaults(deps FrontendDeps) FrontendDeps {
	if deps.StartProcess == nil {
		deps.StartProcess = startProcess
	}
	if deps.RunAsync == nil {
		deps.RunAsync = func(task func()) {
			go task()
		}
	}
	if deps.WaitForReady == nil {
		deps.WaitForReady = waitForFrontendReady
	}
	if deps.OpenBrowser == nil {
		deps.OpenBrowser = winplatform.OpenBrowser
	}
	return deps
}

func scheduleBrowserOpen(openURL string, readyURL string, deps FrontendDeps) {
	if deps.RunAsync == nil || deps.OpenBrowser == nil {
		return
	}

	deps.RunAsync(func() {
		probeURL := readyURL
		if probeURL == "" {
			probeURL = openURL
		}
		if deps.WaitForReady != nil {
			waitCtx, cancel := context.WithTimeout(context.Background(), frontendReadyTimeout)
			waitStartedAt := time.Now()
			logFrontendBrowserEvent(deps.Log, "frontend browser wait begin probe_url=%s open_url=%s", probeURL, openURL)
			err := deps.WaitForReady(waitCtx, probeURL, frontendReadyInterval)
			waitElapsed := time.Since(waitStartedAt).Milliseconds()
			if err != nil {
				logFrontendBrowserEvent(deps.Log, "frontend browser wait fallback probe_url=%s elapsed_ms=%d err=%s", probeURL, waitElapsed, err)
			} else {
				logFrontendBrowserEvent(deps.Log, "frontend browser wait ready probe_url=%s elapsed_ms=%d", probeURL, waitElapsed)
			}
			cancel()
		}

		openStartedAt := time.Now()
		logFrontendBrowserEvent(deps.Log, "frontend browser open begin url=%s", openURL)
		err := deps.OpenBrowser(openURL)
		openElapsed := time.Since(openStartedAt).Milliseconds()
		if err != nil {
			logFrontendBrowserEvent(deps.Log, "frontend browser open failed url=%s elapsed_ms=%d err=%s", openURL, openElapsed, err)
			return
		}
		logFrontendBrowserEvent(deps.Log, "frontend browser open dispatched url=%s elapsed_ms=%d", openURL, openElapsed)
	})
}

func logFrontendBrowserEvent(log func(line string), format string, args ...any) {
	if log == nil {
		return
	}
	log(fmt.Sprintf(format, args...))
}

func waitForFrontendReady(ctx context.Context, rawURL string, interval time.Duration) error {
	address, err := frontendReadyAddress(rawURL)
	if err != nil {
		return httpcheck.WaitForHealthy(ctx, rawURL, interval)
	}
	return waitForTCPReady(ctx, address, interval)
}

func frontendReadyAddress(rawURL string) (string, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return "", err
	}
	if parsed.Host == "" {
		return "", fmt.Errorf("ready url missing host: %s", rawURL)
	}
	return parsed.Host, nil
}

func waitForTCPReady(ctx context.Context, address string, interval time.Duration) error {
	if interval <= 0 {
		interval = 100 * time.Millisecond
	}

	dialer := &net.Dialer{Timeout: interval}
	var lastErr error

	for {
		conn, err := dialer.DialContext(ctx, "tcp", address)
		if err == nil {
			_ = conn.Close()
			return nil
		}
		lastErr = err

		timer := time.NewTimer(interval)
		select {
		case <-ctx.Done():
			timer.Stop()
			if lastErr != nil {
				return fmt.Errorf("wait for tcp ready %s: %w", address, lastErr)
			}
			return fmt.Errorf("wait for tcp ready %s: %w", address, ctx.Err())
		case <-timer.C:
		}
	}
}

func withFrontendCrashDefaults(deps FrontendCrashDeps) FrontendCrashDeps {
	if deps.Now == nil {
		deps.Now = time.Now
	}
	if deps.Sleep == nil {
		deps.Sleep = time.Sleep
	}
	return deps
}

func withFrontendStopDefaults(deps FrontendStopDeps) FrontendStopDeps {
	if deps.IsProcessRunning == nil {
		deps.IsProcessRunning = isProcessRunning
	}
	if deps.KillProcess == nil {
		deps.KillProcess = killProcess
	}
	if deps.FindPIDByPort == nil {
		deps.FindPIDByPort = findPIDByPort
	}
	return deps
}

func stopFrontendHost(current *state.RuntimeState, deps FrontendStopDeps) error {
	if current == nil {
		return nil
	}

	deps = withFrontendStopDefaults(deps)
	gracefulStop := deps.GracefulStop
	if gracefulStop == nil && deps.StaticServer != nil {
		gracefulStop = deps.StaticServer.Stop
	}
	if gracefulStop != nil {
		stopCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		err := gracefulStop(stopCtx)
		cancel()
		if err != nil {
			return err
		}
	}

	pid := current.FrontendHost.PID
	if pid > 0 && deps.IsProcessRunning(pid) {
		if err := deps.KillProcess(pid); err != nil {
			if tolerateMissingProcess(pid, deps.IsProcessRunning, err) != nil {
				return err
			}
		}
	}

	if current.FrontendHost.Port > 0 && deps.FindPIDByPort != nil {
		portPID, err := deps.FindPIDByPort(current.FrontendHost.Port)
		if err == nil && portPID > 0 && portPID != pid && portPID != current.LauncherPID {
			if err := deps.KillProcess(portPID); err != nil {
				if tolerateMissingProcess(portPID, deps.IsProcessRunning, err) != nil {
					return err
				}
			}
		}
	}

	browserOpened := current.FrontendHost.BrowserOpened
	current.FrontendHost = state.FrontendHostState{
		BrowserOpened: browserOpened,
	}
	return nil
}

func tolerateMissingProcess(pid int, isProcessRunning func(pid int) bool, err error) error {
	if err == nil {
		return nil
	}
	if isProcessRunning == nil {
		return err
	}
	if !isProcessRunning(pid) {
		return nil
	}
	return err
}

func frontendDevURL() string {
	return fmt.Sprintf("http://localhost:%d", frontendDevPort)
}

func frontendReadyURL(origin string) string {
	if origin == "" {
		return fmt.Sprintf("http://localhost:%d/", frontendDevPort)
	}
	return origin + "/"
}

func backendOriginFromConfig(cfg config.Config) string {
	if cfg.Backend.Mode == "external" && cfg.Backend.ExternalOrigin != "" {
		return cfg.Backend.ExternalOrigin
	}
	return fmt.Sprintf("http://%s:%d", cfg.Backend.Host, cfg.Backend.Port)
}
