package bootstrap

import (
	"os/exec"

	winplatform "neo-tts/launcher/internal/platform/windows"
)

func configureHiddenCommand(command *exec.Cmd) {
	winplatform.ConfigureCommand(command, winplatform.WindowHidden)
}
