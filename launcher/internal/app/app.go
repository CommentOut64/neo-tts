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
	"neo-tts/launcher/internal/control"
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

type OwnerControlHandle interface {
	Session() control.Session
	Close() error
}

type OwnedProcessGroup interface {
	Attach(pid int) error
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
	StartOwnerControl            func(ctx context.Context, cfg config.Config, shutdown context.CancelFunc) (OwnerControlHandle, error)
	StartOwnedProcessGroup       func(ctx context.Context, cfg config.Config) (OwnedProcessGroup, error)
	EnsureBackend                func(ctx context.Context, cfg config.Config, previous state.RuntimeState, ownerSession *control.Session) (supervisor.BackendResult, error)
	StartFrontend                func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error)
	IsExistingWebInstanceHealthy func(ctx context.Context, existing state.RuntimeState) bool
	WaitForSupervisor            func(ctx context.Context, cfg config.Config, current state.RuntimeState, backendResult supervisor.BackendResult, frontendResult supervisor.FrontendResult) error
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

	// 新 launcher 进程不应继承上一次残留的运行态，否则会把陈旧的
	// FrontendHost.BrowserOpened 等标记误当成当前会话状态。
	current := state.RuntimeState{}
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

	ownerCtx, ownerCancel := context.WithCancel(ctx)
	defer ownerCancel()

	var ownerSession *control.Session
	ownerControl, err := deps.StartOwnerControl(ownerCtx, cfg, ownerCancel)
	if err != nil {
		return RunResult{}, err
	}
	if ownerControl != nil {
		defer ownerControl.Close()
		session := ownerControl.Session()
		ownerSession = &session
	}

	processGroup, err := deps.StartOwnedProcessGroup(ownerCtx, cfg)
	if err != nil {
		return RunResult{}, err
	}
	if processGroup != nil {
		defer processGroup.Close()
		ownerCtx = supervisor.WithOwnedProcessAttacher(ownerCtx, processGroup.Attach)
	}

	backendResult, err := deps.EnsureBackend(ownerCtx, cfg, previous, ownerSession)
	if err != nil {
		return RunResult{}, err
	}
	current = mergeRuntimeState(current, backendResult.State)
	if _, err := deps.SaveState(opts.ProjectRoot, current); err != nil {
		return RunResult{}, err
	}
	logPhase(current, "phase=backend-ready backend_pid="+fmt.Sprint(current.Backend.PID))

	frontendResult, err := deps.StartFrontend(ownerCtx, cfg, current)
	if err != nil {
		return RunResult{}, err
	}
	current = mergeRuntimeState(current, frontendResult.State)
	if _, err := deps.SaveState(opts.ProjectRoot, current); err != nil {
		return RunResult{}, err
	}
	logPhase(current, "phase=running frontend_pid="+fmt.Sprint(current.FrontendHost.PID))

	if err := deps.WaitForSupervisor(ownerCtx, cfg, current, backendResult, frontendResult); err != nil {
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
	if deps.StartOwnerControl == nil {
		deps.StartOwnerControl = func(ctx context.Context, cfg config.Config, shutdown context.CancelFunc) (OwnerControlHandle, error) {
			if cfg.RuntimeMode != "dev" || cfg.FrontendMode != "web" {
				return nil, nil
			}
			return control.StartServer(ctx, control.ServerOptions{
				OnShutdown: shutdown,
			})
		}
	}
	if deps.StartOwnedProcessGroup == nil {
		deps.StartOwnedProcessGroup = func(ctx context.Context, cfg config.Config) (OwnedProcessGroup, error) {
			if cfg.RuntimeMode != "dev" || cfg.FrontendMode != "web" {
				return nil, nil
			}
			return winplatform.CreateOwnedProcessJobObject()
		}
	}
	if deps.EnsureBackend == nil {
		deps.EnsureBackend = func(ctx context.Context, cfg config.Config, previous state.RuntimeState, ownerSession *control.Session) (supervisor.BackendResult, error) {
			return supervisor.EnsureBackend(ctx, cfg, previous, ownerSession, supervisor.BackendDeps{})
		}
	}
	if deps.StartFrontend == nil {
		deps.StartFrontend = func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error) {
			return supervisor.StartFrontendHost(ctx, cfg, current, supervisor.FrontendDeps{
				Log: func(line string) {
					logPhase(current, line)
				},
			})
		}
	}
	if deps.IsExistingWebInstanceHealthy == nil {
		deps.IsExistingWebInstanceHealthy = isExistingWebInstanceHealthy
	}
	if deps.WaitForSupervisor == nil {
		deps.WaitForSupervisor = func(ctx context.Context, cfg config.Config, current state.RuntimeState, backendResult supervisor.BackendResult, frontendResult supervisor.FrontendResult) error {
			if cfg.RuntimeMode == "dev" && cfg.FrontendMode == "web" {
				return supervisor.RunOwner(ctx, cfg, current, supervisor.OwnerDeps{
					BackendExit:   backendResult.Exit,
					FrontendExit:  frontendResult.Exit,
					StaticServer:  frontendResult.StaticServer,
					GracefulStop:  frontendResult.GracefulStop,
				})
			}
			return supervisor.RunLoop(ctx, cfg, current, supervisor.LoopDeps{
				StaticServer: frontendResult.StaticServer,
				GracefulStop: frontendResult.GracefulStop,
			})
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
