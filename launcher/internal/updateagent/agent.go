package updateagent

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	winplatform "neo-tts/launcher/internal/platform/windows"
)

type Options struct {
	PlanPath     string
	BootstrapPID int
}

type Plan struct {
	SchemaVersion            int      `json:"schemaVersion"`
	BootstrapSourcePath      string   `json:"bootstrapSourcePath"`
	BootstrapTargetPath      string   `json:"bootstrapTargetPath"`
	UpdateAgentSourcePath    string   `json:"updateAgentSourcePath,omitempty"`
	UpdateAgentTargetPath    string   `json:"updateAgentTargetPath,omitempty"`
	RelaunchExecutablePath   string   `json:"relaunchExecutablePath"`
	RelaunchArguments        []string `json:"relaunchArguments,omitempty"`
	RelaunchWorkingDirectory string   `json:"relaunchWorkingDirectory"`
}

func ParseOptions(args []string) (Options, error) {
	flagSet := flag.NewFlagSet("update-agent", flag.ContinueOnError)
	flagSet.SetOutput(io.Discard)

	var options Options
	flagSet.StringVar(&options.PlanPath, "plan", "", "path to agent-plan.json")
	flagSet.IntVar(&options.BootstrapPID, "bootstrap-pid", 0, "pid of the bootstrap process to wait for")

	if err := flagSet.Parse(args); err != nil {
		return Options{}, err
	}
	if options.PlanPath == "" {
		return Options{}, fmt.Errorf("update-agent plan path is required")
	}
	if options.BootstrapPID <= 0 {
		return Options{}, fmt.Errorf("update-agent bootstrap pid must be positive")
	}
	return options, nil
}

func LoadPlan(path string) (Plan, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return Plan{}, err
	}

	var plan Plan
	decoder := json.NewDecoder(bytes.NewReader(content))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&plan); err != nil {
		return Plan{}, err
	}
	if err := plan.Validate(); err != nil {
		return Plan{}, err
	}
	return plan, nil
}

func (plan Plan) Validate() error {
	if plan.SchemaVersion != 1 {
		return fmt.Errorf("unsupported agent plan schema version: %d", plan.SchemaVersion)
	}
	if plan.BootstrapSourcePath == "" {
		return fmt.Errorf("agent plan bootstrapSourcePath is required")
	}
	if plan.BootstrapTargetPath == "" {
		return fmt.Errorf("agent plan bootstrapTargetPath is required")
	}
	if plan.RelaunchExecutablePath == "" {
		return fmt.Errorf("agent plan relaunchExecutablePath is required")
	}
	if plan.RelaunchWorkingDirectory == "" {
		return fmt.Errorf("agent plan relaunchWorkingDirectory is required")
	}
	if (plan.UpdateAgentSourcePath == "") != (plan.UpdateAgentTargetPath == "") {
		return fmt.Errorf("agent plan update-agent paths must be set together")
	}
	return nil
}

type ProcessLaunchSpec struct {
	ExecutablePath   string
	Arguments        []string
	WorkingDirectory string
}

type ExecutePlanOptions struct {
	PlanPath              string
	BootstrapPID          int
	CurrentPID            int
	CurrentExecutablePath string
	WaitTimeout           time.Duration
}

type ExecutePlanDeps struct {
	WaitForProcessExit func(int, time.Duration) error
	ReplaceFile        func(string, string) error
	StartProcess       func(ProcessLaunchSpec) error
}

func ExecutePlan(options ExecutePlanOptions, plan Plan, deps ExecutePlanDeps) error {
	if err := plan.Validate(); err != nil {
		return err
	}

	waitForProcessExit := deps.WaitForProcessExit
	if waitForProcessExit == nil {
		waitForProcessExit = waitForProcessExitWithPolling
	}
	replaceFile := deps.ReplaceFile
	if replaceFile == nil {
		replaceFile = replaceFileAtomically
	}
	startProcess := deps.StartProcess
	if startProcess == nil {
		startProcess = startDetachedProcess
	}

	waitTimeout := options.WaitTimeout
	if waitTimeout <= 0 {
		waitTimeout = 30 * time.Second
	}

	currentExecutablePath := filepath.Clean(strings.TrimSpace(options.CurrentExecutablePath))
	if currentExecutablePath == "." || currentExecutablePath == "" {
		executablePath, err := os.Executable()
		if err != nil {
			return fmt.Errorf("resolve current update-agent executable: %w", err)
		}
		currentExecutablePath = filepath.Clean(executablePath)
	}
	isUpdateAgentSecondHop := plan.UpdateAgentSourcePath != "" &&
		plan.UpdateAgentTargetPath != "" &&
		samePath(currentExecutablePath, plan.UpdateAgentSourcePath)

	if err := waitForProcessExit(options.BootstrapPID, waitTimeout); err != nil {
		return fmt.Errorf("wait for bootstrap pid %d: %w", options.BootstrapPID, err)
	}

	if !isUpdateAgentSecondHop {
		if err := replaceFile(plan.BootstrapSourcePath, plan.BootstrapTargetPath); err != nil {
			return fmt.Errorf("replace bootstrap executable: %w", err)
		}
	}

	if plan.UpdateAgentSourcePath != "" && plan.UpdateAgentTargetPath != "" {
		if samePath(currentExecutablePath, plan.UpdateAgentTargetPath) {
			if options.CurrentPID <= 0 {
				return fmt.Errorf("current pid is required for update-agent second hop")
			}
			return startProcess(ProcessLaunchSpec{
				ExecutablePath:   plan.UpdateAgentSourcePath,
				Arguments:        []string{"--plan", options.PlanPath, "--bootstrap-pid", strconv.Itoa(options.CurrentPID)},
				WorkingDirectory: plan.RelaunchWorkingDirectory,
			})
		}
		if !samePath(currentExecutablePath, plan.UpdateAgentTargetPath) {
			if err := replaceFile(plan.UpdateAgentSourcePath, plan.UpdateAgentTargetPath); err != nil {
				return fmt.Errorf("replace update-agent executable: %w", err)
			}
		}
	}

	return startProcess(ProcessLaunchSpec{
		ExecutablePath:   plan.RelaunchExecutablePath,
		Arguments:        append([]string(nil), plan.RelaunchArguments...),
		WorkingDirectory: plan.RelaunchWorkingDirectory,
	})
}

func samePath(left string, right string) bool {
	if strings.TrimSpace(left) == "" || strings.TrimSpace(right) == "" {
		return false
	}
	return strings.EqualFold(filepath.Clean(left), filepath.Clean(right))
}

func waitForProcessExitWithPolling(pid int, timeout time.Duration) error {
	if pid <= 0 {
		return fmt.Errorf("bootstrap pid must be positive")
	}
	deadline := time.Now().Add(timeout)
	for {
		if !winplatform.IsProcessRunning(pid) {
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("timed out after %s", timeout)
		}
		time.Sleep(200 * time.Millisecond)
	}
}

func startDetachedProcess(spec ProcessLaunchSpec) error {
	command := exec.Command(spec.ExecutablePath, spec.Arguments...)
	command.Dir = spec.WorkingDirectory
	if err := command.Start(); err != nil {
		return err
	}
	return command.Process.Release()
}

func replaceFileAtomically(sourcePath string, targetPath string) error {
	source := filepath.Clean(sourcePath)
	target := filepath.Clean(targetPath)
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return err
	}
	sourceFile, err := os.Open(source)
	if err != nil {
		return err
	}
	defer sourceFile.Close()
	sourceInfo, err := sourceFile.Stat()
	if err != nil {
		return err
	}
	tempFile, err := os.CreateTemp(filepath.Dir(target), filepath.Base(target)+".*.tmp")
	if err != nil {
		return err
	}
	tempPath := tempFile.Name()
	keepTemp := false
	defer func() {
		if !keepTemp {
			_ = os.Remove(tempPath)
		}
	}()
	if _, err := io.Copy(tempFile, sourceFile); err != nil {
		_ = tempFile.Close()
		return err
	}
	if err := tempFile.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tempPath, sourceInfo.Mode()); err != nil {
		return err
	}
	if err := replacePreparedFile(tempPath, target); err != nil {
		return err
	}
	keepTemp = true
	return nil
}

func replacePreparedFile(sourcePath string, targetPath string) error {
	if err := os.Rename(sourcePath, targetPath); err == nil {
		return nil
	}
	if err := os.Remove(targetPath); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return os.Rename(sourcePath, targetPath)
}
