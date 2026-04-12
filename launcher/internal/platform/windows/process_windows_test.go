package windows

import (
	"os/exec"
	"strings"
	"testing"
)

func TestBuildProcessInvocationPreservesWorkingDirArgsAndEnv(t *testing.T) {
	invocation := BuildProcessInvocation(ProcessSpec{
		Exe:              "npm.cmd",
		Args:             []string{"run", "dev"},
		WorkingDirectory: `F:\neo-tts\frontend`,
		Environment: map[string]string{
			"VITE_BACKEND_ORIGIN": "http://127.0.0.1:18600",
		},
	})

	if invocation.Executable != "npm.cmd" {
		t.Fatalf("Executable = %q, want npm.cmd", invocation.Executable)
	}
	if len(invocation.Args) != 2 || invocation.Args[0] != "run" || invocation.Args[1] != "dev" {
		t.Fatalf("Args = %#v, want [run dev]", invocation.Args)
	}
	if invocation.WorkingDirectory != `F:\neo-tts\frontend` {
		t.Fatalf("WorkingDirectory = %q, want F:\\neo-tts\\frontend", invocation.WorkingDirectory)
	}
	found := false
	for _, item := range invocation.Environment {
		if item == "VITE_BACKEND_ORIGIN=http://127.0.0.1:18600" {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("Environment missing VITE_BACKEND_ORIGIN: %+v", invocation.Environment)
	}
}

func TestConfigureCommandSetsHideWindowForHiddenStyle(t *testing.T) {
	cmd := exec.Command("powershell", "-NoProfile")

	ConfigureCommand(cmd, WindowHidden)

	if cmd.SysProcAttr == nil || !cmd.SysProcAttr.HideWindow {
		t.Fatal("HideWindow = false, want true")
	}
}

func TestConfigureCommandSetsNewConsoleCreationFlag(t *testing.T) {
	cmd := exec.Command("cmd.exe", "/c", "echo ok")

	ConfigureCommand(cmd, WindowNewConsole)

	if cmd.SysProcAttr == nil || cmd.SysProcAttr.CreationFlags != 0x00000010 {
		t.Fatalf("CreationFlags = %#x, want %#x", cmd.SysProcAttr.CreationFlags, uint32(0x00000010))
	}
}

func TestBuildNativeNewConsoleLaunchConfigDoesNotUseStdHandles(t *testing.T) {
	config, err := buildNativeNewConsoleLaunchConfig(ProcessSpec{
		Exe:              "npm.cmd",
		Args:             []string{"run", "dev"},
		WorkingDirectory: `F:\neo-tts\frontend`,
		Environment: map[string]string{
			"VITE_BACKEND_ORIGIN": "http://127.0.0.1:18600",
		},
		WindowStyle: WindowNewConsole,
		AttachStdIO: false,
	})
	if err != nil {
		t.Fatalf("buildNativeNewConsoleLaunchConfig returned error: %v", err)
	}

	if config.creationFlags&createNewConsoleFlag == 0 {
		t.Fatalf("creationFlags = %#x, want CREATE_NEW_CONSOLE", config.creationFlags)
	}
	if config.creationFlags&createUnicodeEnvironmentFlag == 0 {
		t.Fatalf("creationFlags = %#x, want CREATE_UNICODE_ENVIRONMENT", config.creationFlags)
	}
	if config.startupInfo.Flags != 0 {
		t.Fatalf("startupInfo.Flags = %#x, want 0 so child uses new console std handles", config.startupInfo.Flags)
	}
}

func TestBuildNativeNewConsoleLaunchConfigWrapsCmdScriptsWithCmdExe(t *testing.T) {
	config, err := buildNativeNewConsoleLaunchConfig(ProcessSpec{
		Exe:              "npm.cmd",
		Args:             []string{"run", "dev"},
		WorkingDirectory: `F:\neo-tts\frontend`,
		WindowStyle:      WindowNewConsole,
		AttachStdIO:      false,
	})
	if err != nil {
		t.Fatalf("buildNativeNewConsoleLaunchConfig returned error: %v", err)
	}

	commandLine := utf16SliceToString(config.commandLine)
	if !strings.Contains(strings.ToLower(commandLine), "cmd.exe") {
		t.Fatalf("commandLine = %q, want cmd.exe wrapper", commandLine)
	}
	if !strings.Contains(strings.ToLower(commandLine), "/c") {
		t.Fatalf("commandLine = %q, want /c", commandLine)
	}
	if !strings.Contains(strings.ToLower(commandLine), "npm.cmd") {
		t.Fatalf("commandLine = %q, want npm.cmd target", commandLine)
	}
}

func utf16SliceToString(value []uint16) string {
	if len(value) == 0 {
		return ""
	}
	return string(runeSliceUntilNUL(value))
}

func runeSliceUntilNUL(value []uint16) []rune {
	runes := make([]rune, 0, len(value))
	for _, item := range value {
		if item == 0 {
			break
		}
		runes = append(runes, rune(item))
	}
	return runes
}
