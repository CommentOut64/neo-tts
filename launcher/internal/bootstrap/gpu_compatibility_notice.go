package bootstrap

import (
	"fmt"
	"os/exec"
	"runtime"
)

func StartStartupCompatibilityNotice(message string) error {
	if message == "" || runtime.GOOS != "windows" {
		return nil
	}
	command := newStartupCompatibilityNoticeCommand(message)
	if err := command.Start(); err != nil {
		return err
	}
	return command.Process.Release()
}

func newStartupCompatibilityNoticeCommand(message string) *exec.Cmd {
	return newHiddenPowerShellCommand(startupCompatibilityNoticePowerShellScript(message))
}

func newHiddenPowerShellCommand(script string) *exec.Cmd {
	command := exec.Command(
		"powershell",
		"-NoProfile",
		"-STA",
		"-WindowStyle",
		"Hidden",
		"-ExecutionPolicy",
		"Bypass",
		"-Command",
		script,
	)
	configureHiddenCommand(command)
	return command
}

func startupCompatibilityNoticePowerShellScript(message string) string {
	return fmt.Sprintf(`
Add-Type -AssemblyName PresentationFramework
$message = %s
$title = 'NeoTTS 兼容性提醒'
[void][System.Windows.MessageBox]::Show($message, $title, 'OK', 'Warning')
`, powershellSingleQuote(message))
}
