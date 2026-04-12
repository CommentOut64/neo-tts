package windows

import (
	"os"
	"os/exec"
	"runtime"
	"sort"
	"strings"
	"syscall"
	"unsafe"
	"unicode/utf16"
)

type ProcessSpec struct {
	Exe              string
	Args             []string
	WorkingDirectory string
	Environment      map[string]string
	WindowStyle      WindowStyle
	AttachStdIO      bool
}

type CommandInvocation struct {
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
	createNewConsoleFlag = 0x00000010
	createUnicodeEnvironmentFlag = 0x00000400
)

type nativeNewConsoleLaunchConfig struct {
	executablePath []uint16
	commandLine    []uint16
	currentDir     []uint16
	environment    []uint16
	creationFlags  uint32
	startupInfo    syscall.StartupInfo
}

func BuildProcessInvocation(spec ProcessSpec) CommandInvocation {
	return CommandInvocation{
		Executable:       spec.Exe,
		Args:             append([]string(nil), spec.Args...),
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
			CreationFlags: createNewConsoleFlag,
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

func ShouldUseNativeNewConsoleLaunch(spec ProcessSpec) bool {
	return spec.WindowStyle == WindowNewConsole && !spec.AttachStdIO
}

func StartNativeNewConsoleProcess(spec ProcessSpec) (*os.Process, error) {
	config, err := buildNativeNewConsoleLaunchConfig(spec)
	if err != nil {
		return nil, err
	}

	var processInfo syscall.ProcessInformation
	err = syscall.CreateProcess(
		utf16SlicePtr(config.executablePath),
		utf16SlicePtr(config.commandLine),
		nil,
		nil,
		false,
		config.creationFlags,
		utf16SlicePtr(config.environment),
		utf16SlicePtr(config.currentDir),
		&config.startupInfo,
		&processInfo,
	)
	runtime.KeepAlive(config)
	if err != nil {
		return nil, err
	}
	defer syscall.CloseHandle(processInfo.Thread)

	process, findErr := os.FindProcess(int(processInfo.ProcessId))
	syscall.CloseHandle(processInfo.Process)
	if findErr != nil {
		return nil, findErr
	}
	return process, nil
}

func buildNativeNewConsoleLaunchConfig(spec ProcessSpec) (nativeNewConsoleLaunchConfig, error) {
	invocation := BuildProcessInvocation(spec)

	executablePath, commandArgs, err := resolveNativeLaunchTarget(invocation.Executable, invocation.Args)
	if err != nil {
		return nativeNewConsoleLaunchConfig{}, err
	}

	executablePathUTF16, err := syscall.UTF16FromString(executablePath)
	if err != nil {
		return nativeNewConsoleLaunchConfig{}, err
	}

	commandLine, err := syscall.UTF16FromString(buildWindowsCommandLine(executablePath, commandArgs))
	if err != nil {
		return nativeNewConsoleLaunchConfig{}, err
	}

	currentDir, err := optionalUTF16FromString(invocation.WorkingDirectory)
	if err != nil {
		return nativeNewConsoleLaunchConfig{}, err
	}

	environment, err := buildEnvironmentBlock(invocation.Environment)
	if err != nil {
		return nativeNewConsoleLaunchConfig{}, err
	}

	return nativeNewConsoleLaunchConfig{
		executablePath: executablePathUTF16,
		commandLine:    commandLine,
		currentDir:     currentDir,
		environment:    environment,
		creationFlags:  createNewConsoleFlag | createUnicodeEnvironmentFlag,
		startupInfo: syscall.StartupInfo{
			Cb: uint32(unsafe.Sizeof(syscall.StartupInfo{})),
		},
	}, nil
}

func resolveNativeLaunchTarget(executable string, args []string) (string, []string, error) {
	resolvedExecutable, err := exec.LookPath(executable)
	if err != nil {
		return "", nil, err
	}
	if requiresCommandInterpreter(resolvedExecutable) {
		shellExecutable, shellErr := exec.LookPath("cmd.exe")
		if shellErr != nil {
			return "", nil, shellErr
		}
		wrappedArgs := make([]string, 0, len(args)+3)
		wrappedArgs = append(wrappedArgs, "/d", "/c", resolvedExecutable)
		wrappedArgs = append(wrappedArgs, args...)
		return shellExecutable, wrappedArgs, nil
	}
	return resolvedExecutable, args, nil
}

func requiresCommandInterpreter(executablePath string) bool {
	lower := strings.ToLower(strings.TrimSpace(executablePath))
	return strings.HasSuffix(lower, ".cmd") || strings.HasSuffix(lower, ".bat")
}

func buildWindowsCommandLine(executable string, args []string) string {
	parts := make([]string, 0, len(args)+1)
	parts = append(parts, syscall.EscapeArg(executable))
	for _, arg := range args {
		parts = append(parts, syscall.EscapeArg(arg))
	}
	return strings.Join(parts, " ")
}

func buildEnvironmentBlock(environment []string) ([]uint16, error) {
	if len(environment) == 0 {
		return []uint16{0, 0}, nil
	}

	runes := make([]rune, 0, len(strings.Join(environment, ""))+len(environment)+1)
	for _, item := range environment {
		if strings.ContainsRune(item, '\x00') {
			return nil, syscall.EINVAL
		}
		runes = append(runes, []rune(item)...)
		runes = append(runes, '\x00')
	}
	runes = append(runes, '\x00')
	return utf16.Encode(runes), nil
}

func optionalUTF16FromString(value string) ([]uint16, error) {
	if strings.TrimSpace(value) == "" {
		return nil, nil
	}
	return syscall.UTF16FromString(value)
}

func utf16SlicePtr(value []uint16) *uint16 {
	if len(value) == 0 {
		return nil
	}
	return &value[0]
}
