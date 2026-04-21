package updateagent

import (
	"os"
	"path/filepath"
	"testing"
)

func TestParseOptionsRequiresPlanPathAndBootstrapPID(t *testing.T) {
	if _, err := ParseOptions(nil); err == nil {
		t.Fatal("ParseOptions returned nil error, want missing argument error")
	}
}

func TestLoadPlanReadsMinimalPlan(t *testing.T) {
	planPath := filepath.Join(t.TempDir(), "agent-plan.json")
	if err := os.WriteFile(planPath, []byte(`{
  "schemaVersion": 1,
  "bootstrapSourcePath": "F:\\NeoTTS\\packages\\bootstrap\\1.2.0\\NeoTTS.exe",
  "bootstrapTargetPath": "F:\\NeoTTS\\NeoTTS.exe",
  "relaunchExecutablePath": "F:\\NeoTTS\\NeoTTS.exe",
  "relaunchWorkingDirectory": "F:\\NeoTTS"
}`), 0o644); err != nil {
		t.Fatalf("WriteFile(agent-plan.json) returned error: %v", err)
	}

	got, err := LoadPlan(planPath)
	if err != nil {
		t.Fatalf("LoadPlan returned error: %v", err)
	}

	if got.SchemaVersion != 1 {
		t.Fatalf("SchemaVersion = %d, want 1", got.SchemaVersion)
	}
	if got.BootstrapSourcePath != `F:\NeoTTS\packages\bootstrap\1.2.0\NeoTTS.exe` {
		t.Fatalf("BootstrapSourcePath = %q", got.BootstrapSourcePath)
	}
	if got.BootstrapTargetPath != `F:\NeoTTS\NeoTTS.exe` {
		t.Fatalf("BootstrapTargetPath = %q", got.BootstrapTargetPath)
	}
	if got.RelaunchExecutablePath != `F:\NeoTTS\NeoTTS.exe` {
		t.Fatalf("RelaunchExecutablePath = %q", got.RelaunchExecutablePath)
	}
	if got.RelaunchWorkingDirectory != `F:\NeoTTS` {
		t.Fatalf("RelaunchWorkingDirectory = %q", got.RelaunchWorkingDirectory)
	}
}
