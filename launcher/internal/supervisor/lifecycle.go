package supervisor

import (
	"context"
	"fmt"
	"os"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/logging"
	winplatform "neo-tts/launcher/internal/platform/windows"
	"neo-tts/launcher/internal/state"
)

type lifecycleDeps struct {
	Now              func() time.Time
	Sleep            func(delay time.Duration)
	IsProcessRunning func(pid int) bool
	KillProcess      func(pid int) error
	FindPIDByPort    func(port int) (int, error)
	SaveState        func(current state.RuntimeState) error
	Log              func(line string)
	StartFrontend    func(ctx context.Context, cfg config.Config, current state.RuntimeState) (FrontendResult, error)
}

func withLifecycleDefaults(cfg config.Config, current state.RuntimeState, deps lifecycleDeps) lifecycleDeps {
	if deps.Now == nil {
		deps.Now = time.Now
	}
	if deps.Sleep == nil {
		deps.Sleep = time.Sleep
	}
	if deps.IsProcessRunning == nil {
		deps.IsProcessRunning = isProcessRunning
	}
	if deps.KillProcess == nil {
		deps.KillProcess = killProcess
	}
	if deps.FindPIDByPort == nil {
		deps.FindPIDByPort = findPIDByPort
	}
	if deps.SaveState == nil {
		deps.SaveState = func(next state.RuntimeState) error {
			_, err := state.Save(cfg.ProjectRoot, next)
			return err
		}
	}
	if deps.Log == nil {
		deps.Log = func(line string) {
			formatted := logging.FormatLauncherLine(time.Now(), line)
			_ = logging.Append(current.LogFilePath, formatted)
			if current.RuntimeMode == "dev" {
				_, _ = fmt.Fprintln(os.Stdout, formatted)
			}
		}
	}
	if deps.StartFrontend == nil {
		deps.StartFrontend = func(ctx context.Context, cfg config.Config, current state.RuntimeState) (FrontendResult, error) {
			return StartFrontendHost(ctx, cfg, current, FrontendDeps{})
		}
	}
	return deps
}

func stopOwnedBackend(current *state.RuntimeState, deps lifecycleDeps) error {
	if current == nil || current.Backend.Mode != "owned" || current.Backend.PID <= 0 {
		return nil
	}
	pid := current.Backend.PID
	if deps.IsProcessRunning(pid) {
		if err := deps.KillProcess(pid); err != nil {
			if tolerateMissingProcess(pid, deps.IsProcessRunning, err) != nil {
				return err
			}
		}
	}
	current.Backend.PID = 0
	current.Backend.Command = ""
	return nil
}

func handleShutdown(current state.RuntimeState, deps lifecycleDeps) error {
	stopping := current
	stopping.LastPhase = "stopping"
	if err := deps.SaveState(stopping); err != nil {
		return err
	}
	deps.Log("launcher stopping")

	if err := stopFrontendHost(&stopping, FrontendStopDeps{
		IsProcessRunning: deps.IsProcessRunning,
		KillProcess:      deps.KillProcess,
		FindPIDByPort:    deps.FindPIDByPort,
	}); err != nil {
		return err
	}
	if err := stopOwnedBackend(&stopping, deps); err != nil {
		return err
	}

	stopping.LastPhase = "stopped"
	stopping.LastError = ""
	stopping.FrontendHost.BrowserOpened = false
	if err := deps.SaveState(stopping); err != nil {
		return err
	}
	deps.Log("launcher stopped")
	return nil
}

func mergeLifecycleState(base state.RuntimeState, update state.RuntimeState) state.RuntimeState {
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
	if update.LauncherPID != 0 {
		base.LauncherPID = update.LauncherPID
	}
	return base
}

func findPIDByPort(port int) (int, error) {
	return winplatform.FindListeningPIDByPort(port)
}
