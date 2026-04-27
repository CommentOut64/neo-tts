package bootstrap

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

func StartOfflineUpdateNotice(rootDir string, initialMessage string) error {
	if err := WriteOfflineUpdateNoticeStatus(rootDir, initialMessage); err != nil {
		return err
	}
	paths := offlineUpdateNoticePaths(rootDir)
	_ = os.Remove(paths.donePath)
	if runtime.GOOS != "windows" {
		return nil
	}

	command := newOfflineUpdateNoticeCommand(paths)
	if err := command.Start(); err != nil {
		return err
	}
	return command.Process.Release()
}

func newOfflineUpdateNoticeCommand(paths offlineUpdateNoticePathSet) *exec.Cmd {
	return newHiddenPowerShellCommand(offlineUpdateNoticePowerShellScript(paths.statusPath, paths.donePath))
}

func WriteOfflineUpdateNoticeStatus(rootDir string, message string) error {
	paths := offlineUpdateNoticePaths(rootDir)
	if err := os.MkdirAll(filepath.Dir(paths.statusPath), 0o755); err != nil {
		return err
	}
	return os.WriteFile(paths.statusPath, []byte(strings.TrimSpace(message)), 0o644)
}

func FinishOfflineUpdateNotice(rootDir string) error {
	paths := offlineUpdateNoticePaths(rootDir)
	if err := os.MkdirAll(filepath.Dir(paths.donePath), 0o755); err != nil {
		return err
	}
	return os.WriteFile(paths.donePath, []byte("done"), 0o644)
}

type offlineUpdateNoticePathSet struct {
	statusPath string
	donePath   string
}

func offlineUpdateNoticePaths(rootDir string) offlineUpdateNoticePathSet {
	root := filepath.Clean(rootDir)
	noticeRoot := filepath.Join(root, "cache", "offline-update", "notice")
	return offlineUpdateNoticePathSet{
		statusPath: filepath.Join(noticeRoot, "status.txt"),
		donePath:   filepath.Join(noticeRoot, "done"),
	}
}

func offlineUpdateNoticePowerShellScript(statusPath string, donePath string) string {
	return fmt.Sprintf(`
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName WindowsBase
$statusPath = %s
$donePath = %s
$window = New-Object System.Windows.Window
$window.Title = 'NeoTTS 正在更新'
$window.Width = 420
$window.Height = 150
$window.WindowStartupLocation = 'CenterScreen'
$window.ResizeMode = 'NoResize'
$text = New-Object System.Windows.Controls.TextBlock
$text.Margin = '24'
$text.FontSize = 16
$text.TextWrapping = 'Wrap'
$text.Text = '正在准备离线更新...'
$window.Content = $text
$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(500)
$timer.Add_Tick({
  if (Test-Path -LiteralPath $donePath) {
    $timer.Stop()
    $window.Close()
    return
  }
  if (Test-Path -LiteralPath $statusPath) {
    $next = Get-Content -Raw -LiteralPath $statusPath -ErrorAction SilentlyContinue
    if (-not [string]::IsNullOrWhiteSpace($next)) {
      $text.Text = $next.Trim()
    }
  }
})
$window.Add_Loaded({ $timer.Start() })
[void]$window.ShowDialog()
`, powershellSingleQuote(statusPath), powershellSingleQuote(donePath))
}

func powershellSingleQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "''") + "'"
}
