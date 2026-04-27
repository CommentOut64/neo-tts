package bootstrap

import (
	"path/filepath"
	"testing"
)

func TestParseOptionsDefaultsToExecutableDirectoryAndStableChannel(t *testing.T) {
	executablePath := filepath.Join(`F:\NeoTTS`, "NeoTTS.exe")

	got, err := ParseOptions(nil, executablePath, `F:\workspace`)
	if err != nil {
		t.Fatalf("ParseOptions returned error: %v", err)
	}

	if got.RootDir != filepath.Dir(executablePath) {
		t.Fatalf("RootDir = %q, want %q", got.RootDir, filepath.Dir(executablePath))
	}
	if got.Channel != "stable" {
		t.Fatalf("Channel = %q, want stable", got.Channel)
	}
	if got.StartupSource != "direct" {
		t.Fatalf("StartupSource = %q, want direct", got.StartupSource)
	}
}

func TestParseOptionsResolvesRelativeRootAgainstWorkingDirectory(t *testing.T) {
	workingDir := filepath.Join(`F:\repo`, "desktop")

	got, err := ParseOptions(
		[]string{"--root", `..\portable`, "--channel", "beta", "--startup-source", "update-agent"},
		filepath.Join(workingDir, "NeoTTS.exe"),
		workingDir,
	)
	if err != nil {
		t.Fatalf("ParseOptions returned error: %v", err)
	}

	wantRoot := filepath.Clean(filepath.Join(workingDir, `..\portable`))
	if got.RootDir != wantRoot {
		t.Fatalf("RootDir = %q, want %q", got.RootDir, wantRoot)
	}
	if got.Channel != "beta" {
		t.Fatalf("Channel = %q, want beta", got.Channel)
	}
	if got.StartupSource != "update-agent" {
		t.Fatalf("StartupSource = %q, want update-agent", got.StartupSource)
	}
}
