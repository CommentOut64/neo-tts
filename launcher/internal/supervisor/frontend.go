package supervisor

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"time"

	"neo-tts/launcher/internal/config"
	winplatform "neo-tts/launcher/internal/platform/windows"
	"neo-tts/launcher/internal/state"
	"neo-tts/launcher/internal/web"
)

const (
	frontendDevPort         = 5175
	frontendRestartDelay    = 3 * time.Second
	frontendCrashWindow     = 60 * time.Second
	frontendCrashRetryLimit = 3
)

type FrontendDeps struct {
	StartProcess func(spec winplatform.ProcessSpec) (ProcessHandle, error)
	OpenBrowser  func(url string) error
}

type FrontendCrashDeps struct {
	Now         func() time.Time
	Sleep       func(delay time.Duration)
	StopBackend func() error
}

type FrontendResult struct {
	State        state.RuntimeState
	StaticServer *web.StaticServer
}

type FrontendCrashResult struct {
	State         state.RuntimeState
	CrashTimes    []time.Time
	ShouldRestart bool
}

func StartFrontendHost(ctx context.Context, cfg config.Config, current state.RuntimeState, deps FrontendDeps) (FrontendResult, error) {
	_ = ctx

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
		if err := deps.OpenBrowser(next.FrontendHost.Origin); err != nil {
			return FrontendResult{}, err
		}
		next.FrontendHost.BrowserOpened = true
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
	if deps.OpenBrowser == nil {
		deps.OpenBrowser = winplatform.OpenBrowser
	}
	return deps
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

func frontendDevURL() string {
	return fmt.Sprintf("http://127.0.0.1:%d", frontendDevPort)
}

func backendOriginFromConfig(cfg config.Config) string {
	if cfg.Backend.Mode == "external" && cfg.Backend.ExternalOrigin != "" {
		return cfg.Backend.ExternalOrigin
	}
	return fmt.Sprintf("http://%s:%d", cfg.Backend.Host, cfg.Backend.Port)
}
