package bootstrap

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestOfflineUpdateNoticeStatusAndFinishFiles(t *testing.T) {
	rootDir := t.TempDir()

	if err := WriteOfflineUpdateNoticeStatus(rootDir, "正在准备更新"); err != nil {
		t.Fatalf("WriteOfflineUpdateNoticeStatus returned error: %v", err)
	}

	statusPath := filepath.Join(rootDir, "cache", "offline-update", "notice", "status.txt")
	content, err := os.ReadFile(statusPath)
	if err != nil {
		t.Fatalf("ReadFile(status) returned error: %v", err)
	}
	if string(content) != "正在准备更新" {
		t.Fatalf("status content = %q", content)
	}
	if len(content) >= 3 && content[0] == 0xef && content[1] == 0xbb && content[2] == 0xbf {
		t.Fatal("status file must be UTF-8 without BOM")
	}

	if err := FinishOfflineUpdateNotice(rootDir); err != nil {
		t.Fatalf("FinishOfflineUpdateNotice returned error: %v", err)
	}
	donePath := filepath.Join(rootDir, "cache", "offline-update", "notice", "done")
	if _, err := os.Stat(donePath); err != nil {
		t.Fatalf("Stat(done) returned error: %v", err)
	}
}

func TestOfflineUpdateNoticeScriptWatchesStatusAndDoneFiles(t *testing.T) {
	script := offlineUpdateNoticePowerShellScript(`F:\NeoTTS\cache\offline-update\notice\status.txt`, `F:\NeoTTS\cache\offline-update\notice\done`)

	if !strings.Contains(script, "PresentationFramework") {
		t.Fatalf("script missing WPF assembly: %s", script)
	}
	if !strings.Contains(script, "status.txt") || !strings.Contains(script, "done") {
		t.Fatalf("script missing status/done paths: %s", script)
	}
	if !strings.Contains(script, "NeoTTS 正在更新") {
		t.Fatalf("script missing window title: %s", script)
	}
}

func TestNewOfflineUpdateNoticeCommandHidesWindow(t *testing.T) {
	command := newOfflineUpdateNoticeCommand(offlineUpdateNoticePathSet{
		statusPath: `F:\NeoTTS\cache\offline-update\notice\status.txt`,
		donePath:   `F:\NeoTTS\cache\offline-update\notice\done`,
	})

	if command.SysProcAttr == nil || !command.SysProcAttr.HideWindow {
		t.Fatal("offline update notice command HideWindow = false, want true")
	}
}
