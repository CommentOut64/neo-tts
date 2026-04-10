package windows

import (
	"os/exec"
	"strings"
	"testing"
)

func TestBuildDetachedPowerShellInvocationUsesStartProcess(t *testing.T) {
	invocation := BuildDetachedPowerShellInvocation(ProcessSpec{
		Command:          "npm run dev",
		WorkingDirectory: `F:\neo-tts\frontend`,
	})

	if invocation.Executable != "powershell" {
		t.Fatalf("Executable = %q, want powershell", invocation.Executable)
	}
	text := strings.Join(invocation.Args, " ")
	if !strings.Contains(text, "Start-Process") {
		t.Fatalf("Args = %q, want Start-Process", text)
	}
	if !strings.Contains(text, "-PassThru") {
		t.Fatalf("Args = %q, want -PassThru", text)
	}
	if !strings.Contains(text, "npm run dev") {
		t.Fatalf("Args = %q, want npm run dev", text)
	}
}

func TestConfigureCommandSetsHideWindowForHiddenStyle(t *testing.T) {
	cmd := exec.Command("powershell", "-NoProfile")

	ConfigureCommand(cmd, WindowHidden)

	if cmd.SysProcAttr == nil || !cmd.SysProcAttr.HideWindow {
		t.Fatal("HideWindow = false, want true")
	}
}
