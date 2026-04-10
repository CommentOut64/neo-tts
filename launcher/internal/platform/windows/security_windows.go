package windows

import (
	"os/exec"
	"strings"
)

func IsCurrentProcessElevated() (bool, error) {
	command := exec.Command(
		"powershell",
		"-NoProfile",
		"-Command",
		"[bool](([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))",
	)
	ConfigureCommand(command, WindowHidden)

	output, err := command.Output()
	if err != nil {
		return false, err
	}

	return strings.EqualFold(strings.TrimSpace(string(output)), "True"), nil
}
