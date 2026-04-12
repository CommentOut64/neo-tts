package supervisor

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/control"
	"neo-tts/launcher/internal/httpcheck"
	winplatform "neo-tts/launcher/internal/platform/windows"
	"neo-tts/launcher/internal/state"
)

var (
	ErrPortOccupied         = errors.New("backend port is occupied by an unmanaged process")
	ErrBundledPythonMissing = errors.New("bundled runtime python is missing")
)

const (
	backendHealthInterval = 100 * time.Millisecond
	portProbeTimeout      = 200 * time.Millisecond
	cleanupTimeout        = 2 * time.Second
)

type ProcessHandle struct {
	PID  int
	Exit <-chan error
}

type BackendResult struct {
	State state.RuntimeState
	Exit  <-chan error
}

type BackendDeps struct {
	StartProcess       func(spec winplatform.ProcessSpec) (ProcessHandle, error)
	AttachOwnedProcess func(pid int) error
	WaitForHealthy     func(ctx context.Context, url string, interval time.Duration) error
	CleanupResiduals   func(ctx context.Context, url string) error
	IsProcessRunning   func(pid int) bool
	KillProcess        func(pid int) error
}

type BackendLossDeps struct {
	StopFrontend    func() error
	TakeoverBackend func() error
}

func EnsureBackend(
	ctx context.Context,
	cfg config.Config,
	previous state.RuntimeState,
	ownerSession *control.Session,
	deps BackendDeps,
) (BackendResult, error) {
	deps = withBackendDefaults(deps)
	origin := backendOrigin(cfg)
	healthURL := healthURL(origin)

	if cfg.Backend.Mode == "external" {
		if err := deps.WaitForHealthy(ctx, healthURL, backendHealthInterval); err != nil {
			return BackendResult{}, err
		}
		return BackendResult{
			State: state.RuntimeState{
				RuntimeMode:  cfg.RuntimeMode,
				FrontendMode: cfg.FrontendMode,
				Backend: state.BackendState{
					Mode:   "external",
					Port:   cfg.Backend.Port,
					Origin: origin,
				},
				LastPhase: "backend-ready",
			},
		}, nil
	}

	if err := cleanupOwnedBackend(ctx, cfg, previous, deps); err != nil {
		return BackendResult{}, err
	}

	probeCtx, cancel := context.WithTimeout(ctx, portProbeTimeout)
	defer cancel()
	if err := deps.WaitForHealthy(probeCtx, healthURL, 50*time.Millisecond); err == nil {
		return BackendResult{}, ErrPortOccupied
	}

	pythonExecutable, err := resolvePythonExecutable(cfg)
	if err != nil {
		return BackendResult{}, err
	}

	spec := buildBackendProcessSpec(pythonExecutable, cfg, ownerSession)
	handle, err := deps.StartProcess(spec)
	if err != nil {
		return BackendResult{}, err
	}
	if attach := resolveBackendOwnedProcessAttacher(ctx, deps); attach != nil && handle.PID > 0 {
		if err := attach(handle.PID); err != nil {
			_ = deps.KillProcess(handle.PID)
			return BackendResult{}, err
		}
	}

	command := buildProcessCommandLine(spec.Exe, spec.Args)

	if err := deps.WaitForHealthy(ctx, healthURL, backendHealthInterval); err != nil {
		if handle.PID > 0 {
			_ = deps.KillProcess(handle.PID)
		}
		return BackendResult{}, err
	}

	return BackendResult{
		State: state.RuntimeState{
			RuntimeMode:  cfg.RuntimeMode,
			FrontendMode: cfg.FrontendMode,
			Backend: state.BackendState{
				Mode:    "owned",
				PID:     handle.PID,
				Port:    cfg.Backend.Port,
				Origin:  origin,
				Command: command,
			},
			LastPhase: "backend-ready",
		},
		Exit: handle.Exit,
	}, nil
}

func buildOwnerSessionEnvironment(ownerSession *control.Session) map[string]string {
	if ownerSession == nil {
		return nil
	}

	return map[string]string{
		"NEO_TTS_OWNER_CONTROL_ORIGIN": ownerSession.ControlOrigin,
		"NEO_TTS_OWNER_CONTROL_TOKEN":  ownerSession.ControlToken,
		"NEO_TTS_OWNER_SESSION_ID":     ownerSession.ID,
	}
}

func HandleBackendLoss(current state.RuntimeState, deps BackendLossDeps) (state.RuntimeState, error) {
	current.LastPhase = "degraded"
	switch current.Backend.Mode {
	case "external":
		current.LastError = "external backend became unavailable"
	default:
		current.LastError = "owned backend exited unexpectedly"
	}

	if deps.StopFrontend == nil {
		return current, nil
	}

	if err := deps.StopFrontend(); err != nil {
		current.LastError = current.LastError + ": failed to stop frontend: " + err.Error()
		return current, err
	}

	return current, nil
}

func cleanupOwnedBackend(ctx context.Context, cfg config.Config, previous state.RuntimeState, deps BackendDeps) error {
	if previous.Backend.Mode != "owned" || previous.Backend.PID <= 0 {
		return nil
	}
	if !deps.IsProcessRunning(previous.Backend.PID) {
		return nil
	}

	origin := previous.Backend.Origin
	if origin == "" {
		origin = backendOrigin(cfg)
	}

	cleanupCtx, cancel := context.WithTimeout(ctx, cleanupTimeout)
	defer cancel()

	if err := deps.WaitForHealthy(cleanupCtx, healthURL(origin), backendHealthInterval); err == nil {
		_ = deps.CleanupResiduals(cleanupCtx, cleanupURL(origin))
	}

	if deps.IsProcessRunning(previous.Backend.PID) {
		return deps.KillProcess(previous.Backend.PID)
	}
	return nil
}

func resolvePythonExecutable(cfg config.Config) (string, error) {
	if cfg.RuntimeMode == "product" {
		candidate := resolvePath(cfg.ProjectRoot, cfg.Backend.ProductPython)
		if fileExists(candidate) {
			return candidate, nil
		}
		return "", fmt.Errorf("%w: %s", ErrBundledPythonMissing, candidate)
	}

	candidate := resolvePath(cfg.ProjectRoot, cfg.Backend.DevPython)
	if fileExists(candidate) {
		return candidate, nil
	}
	return "python", nil
}

func buildBackendProcessSpec(
	pythonExecutable string,
	cfg config.Config,
	ownerSession *control.Session,
) winplatform.ProcessSpec {
	return winplatform.ProcessSpec{
		Exe:              pythonExecutable,
		Args:             buildBackendArgs(cfg),
		WorkingDirectory: cfg.ProjectRoot,
		Environment:      buildOwnerSessionEnvironment(ownerSession),
		WindowStyle:      backendWindowStyle(cfg.RuntimeMode),
		AttachStdIO:      shouldAttachBackendStdIO(cfg.RuntimeMode),
	}
}

func buildBackendArgs(cfg config.Config) []string {
	return []string{
		"-m",
		"backend.app.cli",
		"--host",
		cfg.Backend.Host,
		"--port",
		strconv.Itoa(cfg.Backend.Port),
	}
}

func backendOrigin(cfg config.Config) string {
	if cfg.Backend.Mode == "external" && cfg.Backend.ExternalOrigin != "" {
		return strings.TrimRight(cfg.Backend.ExternalOrigin, "/")
	}
	return fmt.Sprintf("http://%s:%d", cfg.Backend.Host, cfg.Backend.Port)
}

func healthURL(origin string) string {
	return strings.TrimRight(origin, "/") + "/health"
}

func cleanupURL(origin string) string {
	return strings.TrimRight(origin, "/") + "/v1/audio/inference/cleanup-residuals"
}

func resolvePath(projectRoot string, candidate string) string {
	if candidate == "" {
		return ""
	}
	if filepath.IsAbs(candidate) {
		return candidate
	}
	return filepath.Join(projectRoot, candidate)
}

func fileExists(path string) bool {
	if path == "" {
		return false
	}
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return !info.IsDir()
}

func buildProcessCommandLine(exe string, args []string) string {
	parts := make([]string, 0, len(args)+1)
	if exe != "" {
		parts = append(parts, exe)
	}
	parts = append(parts, args...)
	return strings.Join(parts, " ")
}

func withBackendDefaults(deps BackendDeps) BackendDeps {
	if deps.StartProcess == nil {
		deps.StartProcess = startProcess
	}
	if deps.WaitForHealthy == nil {
		deps.WaitForHealthy = httpcheck.WaitForHealthy
	}
	if deps.CleanupResiduals == nil {
		deps.CleanupResiduals = cleanupResiduals
	}
	if deps.IsProcessRunning == nil {
		deps.IsProcessRunning = isProcessRunning
	}
	if deps.KillProcess == nil {
		deps.KillProcess = killProcess
	}
	return deps
}

func resolveBackendOwnedProcessAttacher(ctx context.Context, deps BackendDeps) func(pid int) error {
	if deps.AttachOwnedProcess != nil {
		return deps.AttachOwnedProcess
	}
	return attachOwnedProcessFromContext(ctx)
}

func startProcess(spec winplatform.ProcessSpec) (ProcessHandle, error) {
	if winplatform.ShouldUseNativeNewConsoleLaunch(spec) {
		process, err := winplatform.StartNativeNewConsoleProcess(spec)
		if err != nil {
			return ProcessHandle{}, err
		}
		exitCh := make(chan error, 1)
		go func() {
			_, waitErr := process.Wait()
			exitCh <- waitErr
		}()
		return ProcessHandle{
			PID:  process.Pid,
			Exit: exitCh,
		}, nil
	}

	invocation := winplatform.BuildProcessInvocation(spec)
	command := exec.Command(invocation.Executable, invocation.Args...)
	command.Dir = invocation.WorkingDirectory
	command.Env = invocation.Environment
	winplatform.ConfigureCommand(command, spec.WindowStyle)
	winplatform.AttachStandardIO(command, spec.AttachStdIO)
	if err := command.Start(); err != nil {
		return ProcessHandle{}, err
	}
	exitCh := make(chan error, 1)
	go func() {
		exitCh <- command.Wait()
	}()
	return ProcessHandle{
		PID:  command.Process.Pid,
		Exit: exitCh,
	}, nil
}

func cleanupResiduals(ctx context.Context, url string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, nil)
	if err != nil {
		return err
	}

	resp, err := (&http.Client{Timeout: cleanupTimeout}).Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= http.StatusOK && resp.StatusCode < http.StatusBadRequest {
		return nil
	}
	return fmt.Errorf("cleanup residuals returned %s", resp.Status)
}

func backendWindowStyle(runtimeMode string) winplatform.WindowStyle {
	if runtimeMode == "product" {
		return winplatform.WindowHidden
	}
	return winplatform.WindowInheritConsole
}

func shouldAttachBackendStdIO(runtimeMode string) bool {
	return runtimeMode == "dev"
}

func isProcessRunning(pid int) bool {
	return winplatform.IsProcessRunning(pid)
}

func killProcess(pid int) error {
	if pid <= 0 {
		return nil
	}

	command := exec.Command("taskkill", "/F", "/T", "/PID", strconv.Itoa(pid))
	winplatform.ConfigureCommand(command, winplatform.WindowHidden)
	if err := command.Run(); err != nil {
		process, findErr := os.FindProcess(pid)
		if findErr != nil {
			return err
		}
		if killErr := process.Kill(); killErr != nil {
			return err
		}
	}
	return nil
}
