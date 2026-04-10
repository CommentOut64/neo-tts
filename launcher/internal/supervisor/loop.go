package supervisor

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/logging"
	"neo-tts/launcher/internal/state"
)

const loopInterval = time.Second

type LoopDeps struct {
	Tick             <-chan time.Time
	Now              func() time.Time
	Sleep            func(delay time.Duration)
	IsProcessRunning func(pid int) bool
	KillProcess      func(pid int) error
	FindPIDByPort    func(port int) (int, error)
	SaveState        func(current state.RuntimeState) error
	Log              func(line string)
	StartFrontend    func(ctx context.Context, cfg config.Config, current state.RuntimeState) (FrontendResult, error)
}

func RunLoop(ctx context.Context, cfg config.Config, current state.RuntimeState, deps LoopDeps) error {
	deps = withLoopDefaults(cfg, current, deps)

	if ctx.Err() != nil {
		return handleShutdown(current, deps)
	}

	crashTimes := make([]time.Time, 0, frontendCrashRetryLimit)
	tick := deps.Tick
	managedTicker := (*time.Ticker)(nil)
	if tick == nil {
		managedTicker = time.NewTicker(loopInterval)
		defer managedTicker.Stop()
		tick = managedTicker.C
	}

	for {
		select {
		case <-ctx.Done():
			return handleShutdown(current, deps)
		case <-tick:
			next, restartWindow, err := stepLoop(ctx, cfg, current, crashTimes, deps)
			if err != nil {
				return err
			}
			current = next
			crashTimes = restartWindow
		}
	}
}

func stepLoop(
	ctx context.Context,
	cfg config.Config,
	current state.RuntimeState,
	crashTimes []time.Time,
	deps LoopDeps,
) (state.RuntimeState, []time.Time, error) {
	if isOwnedBackendDown(current, deps) {
		deps.Log(fmt.Sprintf("backend lost pid=%d", current.Backend.PID))
		next, err := HandleBackendLoss(current, BackendLossDeps{
			StopFrontend: func() error {
				return stopFrontendHost(&current, deps)
			},
		})
		if err != nil {
			current = next
			_ = deps.SaveState(current)
			return current, crashTimes, err
		}
		next.Backend.PID = 0
		next.FrontendHost.PID = 0
		if err := deps.SaveState(next); err != nil {
			return current, crashTimes, err
		}
		return next, crashTimes, nil
	}

	if isFrontendDown(current, deps) {
		deps.Log(fmt.Sprintf("frontend host lost pid=%d", current.FrontendHost.PID))
		result, err := HandleFrontendCrash(current, crashTimes, FrontendCrashDeps{
			Now:   deps.Now,
			Sleep: deps.Sleep,
			StopBackend: func() error {
				return stopOwnedBackend(&current, deps)
			},
		})
		if err != nil {
			current = result.State
			_ = deps.SaveState(current)
			return current, result.CrashTimes, err
		}

		next := result.State
		next.FrontendHost.PID = 0
		if err := deps.SaveState(next); err != nil {
			return current, result.CrashTimes, err
		}
		if !result.ShouldRestart {
			deps.Log("frontend host entered degraded state")
			return next, result.CrashTimes, nil
		}

		restarted, err := deps.StartFrontend(ctx, cfg, next)
		if err != nil {
			next.LastPhase = "degraded"
			next.LastError = "failed to restart frontend host: " + err.Error()
			if saveErr := deps.SaveState(next); saveErr != nil {
				return current, result.CrashTimes, saveErr
			}
			deps.Log(next.LastError)
			return next, result.CrashTimes, nil
		}

		next = mergeLoopState(next, restarted.State)
		if err := deps.SaveState(next); err != nil {
			return current, result.CrashTimes, err
		}
		deps.Log(fmt.Sprintf("frontend host restarted pid=%d", next.FrontendHost.PID))
		return next, result.CrashTimes, nil
	}

	return current, crashTimes, nil
}

func withLoopDefaults(cfg config.Config, current state.RuntimeState, deps LoopDeps) LoopDeps {
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

func isOwnedBackendDown(current state.RuntimeState, deps LoopDeps) bool {
	return current.Backend.Mode == "owned" && current.Backend.PID > 0 && !deps.IsProcessRunning(current.Backend.PID)
}

func isFrontendDown(current state.RuntimeState, deps LoopDeps) bool {
	return current.FrontendHost.PID > 0 && !deps.IsProcessRunning(current.FrontendHost.PID)
}

func stopFrontendHost(current *state.RuntimeState, deps LoopDeps) error {
	if current == nil || current.FrontendHost.PID <= 0 {
		return nil
	}
	pid := current.FrontendHost.PID
	if deps.IsProcessRunning(pid) {
		if err := deps.KillProcess(pid); err != nil {
			return err
		}
	}
	current.FrontendHost.PID = 0
	current.FrontendHost.Command = ""
	if current.FrontendHost.Port > 0 && deps.FindPIDByPort != nil {
		portPID, err := deps.FindPIDByPort(current.FrontendHost.Port)
		if err == nil && portPID > 0 && portPID != pid {
			if err := deps.KillProcess(portPID); err != nil {
				return err
			}
		}
	}
	return nil
}

func stopOwnedBackend(current *state.RuntimeState, deps LoopDeps) error {
	if current == nil || current.Backend.Mode != "owned" || current.Backend.PID <= 0 {
		return nil
	}
	pid := current.Backend.PID
	if deps.IsProcessRunning(pid) {
		if err := deps.KillProcess(pid); err != nil {
			return err
		}
	}
	current.Backend.PID = 0
	current.Backend.Command = ""
	return nil
}

func handleShutdown(current state.RuntimeState, deps LoopDeps) error {
	stopping := current
	stopping.LastPhase = "stopping"
	if err := deps.SaveState(stopping); err != nil {
		return err
	}
	deps.Log("launcher stopping")

	if err := stopFrontendHost(&stopping, deps); err != nil {
		return err
	}
	if err := stopOwnedBackend(&stopping, deps); err != nil {
		return err
	}

	stopping.LastPhase = "stopped"
	stopping.LastError = ""
	if err := deps.SaveState(stopping); err != nil {
		return err
	}
	deps.Log("launcher stopped")
	return nil
}

func mergeLoopState(base state.RuntimeState, update state.RuntimeState) state.RuntimeState {
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
	if port <= 0 {
		return 0, nil
	}

	command := exec.Command(
		"powershell",
		"-NoProfile",
		"-Command",
		fmt.Sprintf(
			"$line = Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess; if ($line) { $line }",
			port,
		),
	)
	output, err := command.Output()
	if err != nil {
		return 0, err
	}

	text := strings.TrimSpace(string(output))
	if text == "" {
		return 0, nil
	}

	pid, err := strconv.Atoi(text)
	if err != nil {
		return 0, err
	}
	return pid, nil
}
