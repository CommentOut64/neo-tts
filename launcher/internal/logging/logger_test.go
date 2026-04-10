package logging

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestBootstrapLoggerCreatesSessionLogFile(t *testing.T) {
	projectRoot := t.TempDir()

	session, err := Bootstrap(projectRoot, StartupContext{
		WorkingDirectory: projectRoot,
		ExecutablePath:   filepath.Join(projectRoot, "launcher.exe"),
		Arguments:        []string{"--runtime-mode", "dev"},
		StartupSource:    "double-click",
	})
	if err != nil {
		t.Fatalf("Bootstrap returned error: %v", err)
	}

	if session.LogFilePath == "" {
		t.Fatal("LogFilePath is empty")
	}
	if _, err := os.Stat(session.LogFilePath); err != nil {
		t.Fatalf("Stat(%q): %v", session.LogFilePath, err)
	}
	if !strings.Contains(session.LogFilePath, filepath.Join("logs", "launcher")) {
		t.Fatalf("LogFilePath = %q, want logs/launcher segment", session.LogFilePath)
	}
}

func TestBootstrapLoggerWritesStartupHeader(t *testing.T) {
	projectRoot := t.TempDir()

	session, err := Bootstrap(projectRoot, StartupContext{
		WorkingDirectory: projectRoot,
		ExecutablePath:   filepath.Join(projectRoot, "launcher.exe"),
		Arguments:        []string{"--runtime-mode", "dev"},
		IsElevated:       true,
		StartupSource:    "double-click",
	})
	if err != nil {
		t.Fatalf("Bootstrap returned error: %v", err)
	}

	content, err := os.ReadFile(session.LogFilePath)
	if err != nil {
		t.Fatalf("ReadFile(%q): %v", session.LogFilePath, err)
	}

	text := string(content)
	if !strings.Contains(text, "[INFO] [launcher] startup begin") {
		t.Fatalf("log file missing startup marker: %q", text)
	}
	if !strings.Contains(text, "double-click") {
		t.Fatalf("log file missing startup source: %q", text)
	}
	if !strings.Contains(text, "elevated=true") {
		t.Fatalf("log file missing elevation flag: %q", text)
	}
}

func TestAppendPersistsAdditionalLogLine(t *testing.T) {
	projectRoot := t.TempDir()

	session, err := Bootstrap(projectRoot, StartupContext{
		WorkingDirectory: projectRoot,
		ExecutablePath:   filepath.Join(projectRoot, "launcher.exe"),
		StartupSource:    "direct",
	})
	if err != nil {
		t.Fatalf("Bootstrap returned error: %v", err)
	}

	if err := Append(session.LogFilePath, "phase=backend-ready"); err != nil {
		t.Fatalf("Append returned error: %v", err)
	}

	content, err := os.ReadFile(session.LogFilePath)
	if err != nil {
		t.Fatalf("ReadFile(%q): %v", session.LogFilePath, err)
	}
	if !strings.Contains(string(content), "phase=backend-ready") {
		t.Fatalf("content = %q, want appended line", string(content))
	}
}

func TestFormatLauncherLineAddsTimestampAndTag(t *testing.T) {
	got := FormatLauncherLine(time.Date(2026, 4, 10, 21, 21, 21, 157000000, time.Local), "phase=running")

	want := "21:21:21.157 [INFO] [launcher] phase=running"
	if got != want {
		t.Fatalf("FormatLauncherLine = %q, want %q", got, want)
	}
}
