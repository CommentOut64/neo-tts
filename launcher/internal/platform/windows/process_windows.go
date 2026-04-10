package windows

import (
	"os"
	"os/exec"
	"sort"
	"strings"
	"syscall"
)

type ProcessSpec struct {
	Command          string
	WorkingDirectory string
	Environment      map[string]string
	WindowStyle      WindowStyle
	AttachStdIO      bool
}

type PowerShellInvocation struct {
	Executable       string
	Args             []string
	WorkingDirectory string
	Environment      []string
}

type WindowStyle string

const (
	WindowInheritConsole WindowStyle = "inherit-console"
	WindowHidden         WindowStyle = "hidden"
	WindowNewConsole     WindowStyle = "new-console"
)

func BuildPowerShellInvocation(spec ProcessSpec) PowerShellInvocation {
	return PowerShellInvocation{
		Executable:       "powershell",
		Args:             []string{"-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", spec.Command},
		WorkingDirectory: spec.WorkingDirectory,
		Environment:      mergeEnvironment(spec.Environment),
	}
}

func BuildDetachedPowerShellInvocation(spec ProcessSpec) PowerShellInvocation {
	childArgs := "@('-NoProfile','-ExecutionPolicy','Bypass','-Command'," + quotePowerShellLiteral(spec.Command) + ")"
	command := "$p = Start-Process -FilePath 'powershell' -WorkingDirectory " +
		quotePowerShellLiteral(spec.WorkingDirectory) +
		" -ArgumentList " + childArgs + " -PassThru; $p.Id"

	return PowerShellInvocation{
		Executable:       "powershell",
		Args:             []string{"-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command},
		WorkingDirectory: spec.WorkingDirectory,
		Environment:      mergeEnvironment(spec.Environment),
	}
}

func mergeEnvironment(overrides map[string]string) []string {
	envMap := make(map[string]string, len(overrides))
	for _, item := range os.Environ() {
		key, value, ok := splitEnv(item)
		if !ok {
			continue
		}
		envMap[key] = value
	}
	for key, value := range overrides {
		envMap[key] = value
	}

	keys := make([]string, 0, len(envMap))
	for key := range envMap {
		keys = append(keys, key)
	}
	sort.Strings(keys)

	result := make([]string, 0, len(keys))
	for _, key := range keys {
		result = append(result, key+"="+envMap[key])
	}
	return result
}

func splitEnv(item string) (string, string, bool) {
	for index := 0; index < len(item); index++ {
		if item[index] == '=' {
			return item[:index], item[index+1:], true
		}
	}
	return "", "", false
}

func quotePowerShellLiteral(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "''") + "'"
}

func ConfigureCommand(cmd *exec.Cmd, style WindowStyle) {
	if cmd == nil {
		return
	}

	switch style {
	case WindowHidden:
		cmd.SysProcAttr = &syscall.SysProcAttr{
			HideWindow: true,
		}
	case WindowNewConsole:
		cmd.SysProcAttr = &syscall.SysProcAttr{
			CreationFlags: 0x00000010,
		}
	}
}

func AttachStandardIO(cmd *exec.Cmd, enabled bool) {
	if cmd == nil || !enabled {
		return
	}
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
}
