package app

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/logging"
	winplatform "neo-tts/launcher/internal/platform/windows"
	"neo-tts/launcher/internal/state"
	"neo-tts/launcher/internal/supervisor"
)

type StartupContext struct {
	ProjectRoot   string
	StartupSource string
	IsElevated    bool
	InstanceName  string
}

const (
	PhaseBackendReady       = "backend-ready"
	PhaseDegraded           = "degraded"
	PhaseRunning            = "running"
	PhaseFrontendRestarting = "frontend-restarting"
)

var ErrAlreadyRunning = errors.New("launcher instance is already running")

type InstanceLock interface {
	Close() error
}

type RunOptions struct {
	ProjectRoot   string
	Overrides     config.CLIOverrides
	StartupSource string
	LogFilePath   string
}

type AppDeps struct {
	LoadConfig                   func(projectRoot string, overrides config.CLIOverrides) (config.Config, error)
	BuildStartupContext          func(projectRoot string, startupSource string) (StartupContext, error)
	AcquireInstanceLock          func(name string) (InstanceLock, bool, error)
	LoadState                    func(projectRoot string) (state.RuntimeState, error)
	SaveState                    func(projectRoot string, runtimeState state.RuntimeState) (string, error)
	EnsureBackend                func(ctx context.Context, cfg config.Config, previous state.RuntimeState) (supervisor.BackendResult, error)
	StartFrontend                func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error)
	IsExistingWebInstanceHealthy func(ctx context.Context, existing state.RuntimeState) bool
	WaitForSupervisor            func(ctx context.Context, cfg config.Config, current state.RuntimeState) error
}

type RunResult struct {
	Config     config.Config
	State      state.RuntimeState
	SilentExit bool
}

func BuildInstanceName(projectRoot string) string {
	return winplatform.InstanceName(projectRoot)
}

func BuildStartupContext(projectRoot string, startupSource string) (StartupContext, error) {
	isElevated, err := winplatform.IsCurrentProcessElevated()
	if err != nil {
		return StartupContext{}, err
	}

	return StartupContext{
		ProjectRoot:   projectRoot,
		StartupSource: startupSource,
		IsElevated:    isElevated,
		InstanceName:  BuildInstanceName(projectRoot),
	}, nil
}

func Run(ctx context.Context, opts RunOptions, deps AppDeps) (RunResult, error) {
	deps = withAppDefaults(deps)

	cfg, err := deps.LoadConfig(opts.ProjectRoot, opts.Overrides)
	if err != nil {
		return RunResult{}, err
	}

	startup, err := deps.BuildStartupContext(opts.ProjectRoot, opts.StartupSource)
	if err != nil {
		return RunResult{}, err
	}

	lock, acquired, err := deps.AcquireInstanceLock(startup.InstanceName)
	if err != nil {
		return RunResult{}, err
	}
	if lock != nil {
		defer lock.Close()
	}

	previous, err := deps.LoadState(opts.ProjectRoot)
	if err != nil {
		return RunResult{}, err
	}

	if !acquired {
		if cfg.FrontendMode == "web" && deps.IsExistingWebInstanceHealthy(ctx, previous) {
			return RunResult{
				Config:     cfg,
				State:      previous,
				SilentExit: true,
			}, nil
		}
		return RunResult{}, ErrAlreadyRunning
	}

	current := previous
	current.LauncherPID = os.Getpid()
	current.RuntimeMode = cfg.RuntimeMode
	current.FrontendMode = cfg.FrontendMode
	current.StartupSource = startup.StartupSource
	current.IsElevated = startup.IsElevated
	if opts.LogFilePath != "" {
		current.LogFilePath = opts.LogFilePath
	}
	current.LastPhase = "booting"

	if _, err := deps.SaveState(opts.ProjectRoot, current); err != nil {
		return RunResult{}, err
	}
	logPhase(current, "phase=booting")

	backendResult, err := deps.EnsureBackend(ctx, cfg, previous)
	if err != nil {
		return RunResult{}, err
	}
	current = mergeRuntimeState(current, backendResult.State)
	if _, err := deps.SaveState(opts.ProjectRoot, current); err != nil {
		return RunResult{}, err
	}
	logPhase(current, "phase=backend-ready backend_pid="+fmt.Sprint(current.Backend.PID))

	frontendResult, err := deps.StartFrontend(ctx, cfg, current)
	if err != nil {
		return RunResult{}, err
	}
	current = mergeRuntimeState(current, frontendResult.State)
	if _, err := deps.SaveState(opts.ProjectRoot, current); err != nil {
		return RunResult{}, err
	}
	logPhase(current, "phase=running frontend_pid="+fmt.Sprint(current.FrontendHost.PID))

	if err := deps.WaitForSupervisor(ctx, cfg, current); err != nil {
		return RunResult{}, err
	}

	return RunResult{
		Config: cfg,
		State:  current,
	}, nil
}

func mergeRuntimeState(base state.RuntimeState, update state.RuntimeState) state.RuntimeState {
	if update.LauncherPID != 0 {
		base.LauncherPID = update.LauncherPID
	}
	if update.RuntimeMode != "" {
		base.RuntimeMode = update.RuntimeMode
	}
	if update.FrontendMode != "" {
		base.FrontendMode = update.FrontendMode
	}
	if update.StartupSource != "" {
		base.StartupSource = update.StartupSource
	}
	if update.IsElevated {
		base.IsElevated = true
	}
	if update.Backend != (state.BackendState{}) {
		base.Backend = update.Backend
	}
	if update.FrontendHost != (state.FrontendHostState{}) {
		base.FrontendHost = update.FrontendHost
	}
	if update.LastPhase != "" {
		base.LastPhase = update.LastPhase
	}
	if update.LastError != "" {
		base.LastError = update.LastError
	}
	if update.LogFilePath != "" {
		base.LogFilePath = update.LogFilePath
	}
	return base
}

func withAppDefaults(deps AppDeps) AppDeps {
	if deps.LoadConfig == nil {
		deps.LoadConfig = config.Load
	}
	if deps.BuildStartupContext == nil {
		deps.BuildStartupContext = BuildStartupContext
	}
	if deps.AcquireInstanceLock == nil {
		deps.AcquireInstanceLock = func(name string) (InstanceLock, bool, error) {
			return winplatform.TryAcquireInstanceLock(name)
		}
	}
	if deps.LoadState == nil {
		deps.LoadState = state.Load
	}
	if deps.SaveState == nil {
		deps.SaveState = state.Save
	}
	if deps.EnsureBackend == nil {
		deps.EnsureBackend = func(ctx context.Context, cfg config.Config, previous state.RuntimeState) (supervisor.BackendResult, error) {
			return supervisor.EnsureBackend(ctx, cfg, previous, supervisor.BackendDeps{})
		}
	}
	if deps.StartFrontend == nil {
		deps.StartFrontend = func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error) {
			return supervisor.StartFrontendHost(ctx, cfg, current, supervisor.FrontendDeps{})
		}
	}
	if deps.IsExistingWebInstanceHealthy == nil {
		deps.IsExistingWebInstanceHealthy = isExistingWebInstanceHealthy
	}
	if deps.WaitForSupervisor == nil {
		deps.WaitForSupervisor = func(ctx context.Context, cfg config.Config, current state.RuntimeState) error {
			return supervisor.RunLoop(ctx, cfg, current, supervisor.LoopDeps{})
		}
	}
	return deps
}

func isExistingWebInstanceHealthy(ctx context.Context, existing state.RuntimeState) bool {
	origin := strings.TrimRight(existing.FrontendHost.Origin, "/")
	if origin == "" {
		return false
	}

	probeCtx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
	defer cancel()

	req, err := http.NewRequestWithContext(probeCtx, http.MethodGet, origin+"/", nil)
	if err != nil {
		return false
	}

	resp, err := (&http.Client{Timeout: 500 * time.Millisecond}).Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	return resp.StatusCode >= http.StatusOK && resp.StatusCode < http.StatusBadRequest
}

func logPhase(current state.RuntimeState, line string) {
	formatted := logging.FormatLauncherLine(time.Now(), line)
	_ = logging.Append(current.LogFilePath, formatted)
	if current.RuntimeMode == "dev" {
		_, _ = fmt.Fprintln(os.Stdout, formatted)
	}
}
