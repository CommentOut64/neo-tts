package supervisor

import (
	"context"
	"fmt"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/state"
)

type OwnerDeps struct {
	BackendExit      <-chan error
	FrontendExit     <-chan error
	Now              func() time.Time
	Sleep            func(delay time.Duration)
	IsProcessRunning func(pid int) bool
	KillProcess      func(pid int) error
	FindPIDByPort    func(port int) (int, error)
	SaveState        func(current state.RuntimeState) error
	Log              func(line string)
	StartFrontend    func(ctx context.Context, cfg config.Config, current state.RuntimeState) (FrontendResult, error)
}

func RunOwner(ctx context.Context, cfg config.Config, current state.RuntimeState, deps OwnerDeps) error {
	deps = withOwnerDefaults(cfg, current, deps)

	backendExit := deps.BackendExit
	frontendExit := deps.FrontendExit
	crashTimes := make([]time.Time, 0, frontendCrashRetryLimit)

	for {
		select {
		case <-ctx.Done():
			return handleShutdown(current, toLifecycleDeps(cfg, current, deps))
		case err := <-backendExit:
			deps.Log(fmt.Sprintf("backend lost pid=%d err=%v", current.Backend.PID, err))
			next, handleErr := HandleBackendLoss(current, BackendLossDeps{
				StopFrontend: func() error {
					return stopFrontendHost(&current, FrontendStopDeps{
						IsProcessRunning: deps.IsProcessRunning,
						KillProcess:      deps.KillProcess,
						FindPIDByPort:    deps.FindPIDByPort,
					})
				},
			})
			if handleErr != nil {
				current = next
				_ = deps.SaveState(current)
				return handleErr
			}
			next.Backend.PID = 0
			next.Backend.Command = ""
			next.FrontendHost.PID = 0
			if err := deps.SaveState(next); err != nil {
				return err
			}
			current = next
			backendExit = nil
			frontendExit = nil
		case err := <-frontendExit:
			deps.Log(fmt.Sprintf("frontend host lost pid=%d err=%v", current.FrontendHost.PID, err))
			result, handleErr := HandleFrontendCrash(current, crashTimes, FrontendCrashDeps{
				Now:   deps.Now,
				Sleep: deps.Sleep,
				StopBackend: func() error {
					return stopOwnedBackend(&current, toLifecycleDeps(cfg, current, deps))
				},
			})
			if handleErr != nil {
				current = result.State
				_ = deps.SaveState(current)
				return handleErr
			}

			next := result.State
			next.FrontendHost.PID = 0
			if !result.ShouldRestart {
				next.Backend.PID = 0
				next.Backend.Command = ""
			}
			if err := deps.SaveState(next); err != nil {
				return err
			}
			if !result.ShouldRestart {
				deps.Log("frontend host entered degraded state")
				current = next
				crashTimes = result.CrashTimes
				backendExit = nil
				frontendExit = nil
				continue
			}

			restarted, err := deps.StartFrontend(ctx, cfg, next)
			if err != nil {
				next.LastPhase = "degraded"
				next.LastError = "failed to restart frontend host: " + err.Error()
				if saveErr := deps.SaveState(next); saveErr != nil {
					return saveErr
				}
				deps.Log(next.LastError)
				current = next
				crashTimes = result.CrashTimes
				frontendExit = nil
				continue
			}

			next = mergeLifecycleState(next, restarted.State)
			frontendExit = restarted.Exit
			if err := deps.SaveState(next); err != nil {
				return err
			}
			deps.Log(fmt.Sprintf("frontend host restarted pid=%d", next.FrontendHost.PID))
			current = next
			crashTimes = result.CrashTimes
		}
	}
}

func withOwnerDefaults(cfg config.Config, current state.RuntimeState, deps OwnerDeps) OwnerDeps {
	lifecycle := withLifecycleDefaults(cfg, current, lifecycleDeps{
		Now:              deps.Now,
		Sleep:            deps.Sleep,
		IsProcessRunning: deps.IsProcessRunning,
		KillProcess:      deps.KillProcess,
		FindPIDByPort:    deps.FindPIDByPort,
		SaveState:        deps.SaveState,
		Log:              deps.Log,
		StartFrontend:    deps.StartFrontend,
	})

	deps.Now = lifecycle.Now
	deps.Sleep = lifecycle.Sleep
	deps.IsProcessRunning = lifecycle.IsProcessRunning
	deps.KillProcess = lifecycle.KillProcess
	deps.FindPIDByPort = lifecycle.FindPIDByPort
	deps.SaveState = lifecycle.SaveState
	deps.Log = lifecycle.Log
	deps.StartFrontend = lifecycle.StartFrontend
	return deps
}

func toLifecycleDeps(cfg config.Config, current state.RuntimeState, deps OwnerDeps) lifecycleDeps {
	return withLifecycleDefaults(cfg, current, lifecycleDeps{
		Now:              deps.Now,
		Sleep:            deps.Sleep,
		IsProcessRunning: deps.IsProcessRunning,
		KillProcess:      deps.KillProcess,
		FindPIDByPort:    deps.FindPIDByPort,
		SaveState:        deps.SaveState,
		Log:              deps.Log,
		StartFrontend:    deps.StartFrontend,
	})
}
