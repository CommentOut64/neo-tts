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
	command := exec.Command(
		"powershell",
		"-NoProfile",
		"-STA",
		"-WindowStyle",
		"Hidden",
		"-ExecutionPolicy",
		"Bypass",
		"-Command",
		startupCompatibilityNoticePowerShellScript(message),
	)
	if err := command.Start(); err != nil {
		return err
	}
	return command.Process.Release()
}

func startupCompatibilityNoticePowerShellScript(message string) string {
	return fmt.Sprintf(`
Add-Type -AssemblyName PresentationFramework
$message = %s
$title = 'NeoTTS 兼容性提醒'
[void][System.Windows.MessageBox]::Show($message, $title, 'OK', 'Warning')
`, powershellSingleQuote(message))
}
