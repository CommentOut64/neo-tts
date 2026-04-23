package updateagent

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
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

func TestExecutePlanWaitsForBootstrapExitReplacesBootstrapAndRelaunches(t *testing.T) {
	plan := Plan{
		SchemaVersion:            1,
		BootstrapSourcePath:      `F:\NeoTTS\packages\bootstrap\1.2.0\NeoTTS.exe`,
		BootstrapTargetPath:      `F:\NeoTTS\NeoTTS.exe`,
		RelaunchExecutablePath:   `F:\NeoTTS\NeoTTS.exe`,
		RelaunchWorkingDirectory: `F:\NeoTTS`,
		RelaunchArguments:        []string{"--startup-source", "update-agent"},
	}

	var waitedPID int
	var replaced [][2]string
	var launched ProcessLaunchSpec
	err := ExecutePlan(
		ExecutePlanOptions{
			PlanPath:              `F:\NeoTTS\agent-plan.json`,
			BootstrapPID:          3456,
			CurrentPID:            4567,
			CurrentExecutablePath: `F:\NeoTTS\NeoTTSUpdateAgent.exe`,
			WaitTimeout:           5 * time.Second,
		},
		plan,
		ExecutePlanDeps{
			WaitForProcessExit: func(pid int, timeout time.Duration) error {
				waitedPID = pid
				if timeout != 5*time.Second {
					t.Fatalf("timeout = %s, want 5s", timeout)
				}
				return nil
			},
			ReplaceFile: func(sourcePath string, targetPath string) error {
				replaced = append(replaced, [2]string{sourcePath, targetPath})
				return nil
			},
			StartProcess: func(spec ProcessLaunchSpec) error {
				launched = spec
				return nil
			},
		},
	)
	if err != nil {
		t.Fatalf("ExecutePlan returned error: %v", err)
	}

	if waitedPID != 3456 {
		t.Fatalf("waited pid = %d, want 3456", waitedPID)
	}
	if len(replaced) != 1 {
		t.Fatalf("replace calls = %d, want 1", len(replaced))
	}
	if replaced[0][0] != plan.BootstrapSourcePath || replaced[0][1] != plan.BootstrapTargetPath {
		t.Fatalf("replace bootstrap = %#v, want source=%q target=%q", replaced[0], plan.BootstrapSourcePath, plan.BootstrapTargetPath)
	}
	if launched.ExecutablePath != plan.RelaunchExecutablePath {
		t.Fatalf("relaunch executable = %q, want %q", launched.ExecutablePath, plan.RelaunchExecutablePath)
	}
	if launched.WorkingDirectory != plan.RelaunchWorkingDirectory {
		t.Fatalf("relaunch working dir = %q, want %q", launched.WorkingDirectory, plan.RelaunchWorkingDirectory)
	}
	if len(launched.Arguments) != 2 || launched.Arguments[0] != "--startup-source" || launched.Arguments[1] != "update-agent" {
		t.Fatalf("relaunch args = %#v", launched.Arguments)
	}
}

func TestExecutePlanUsesSecondHopWhenUpdatingUpdateAgentItself(t *testing.T) {
	rootDir := t.TempDir()
	planPath := filepath.Join(rootDir, "agent-plan.json")
	plan := Plan{
		SchemaVersion:            1,
		BootstrapSourcePath:      filepath.Join(rootDir, "packages", "bootstrap", "1.2.0", "NeoTTS.exe"),
		BootstrapTargetPath:      filepath.Join(rootDir, "NeoTTS.exe"),
		UpdateAgentSourcePath:    filepath.Join(rootDir, "packages", "update-agent", "1.2.0", "NeoTTSUpdateAgent.exe"),
		UpdateAgentTargetPath:    filepath.Join(rootDir, "NeoTTSUpdateAgent.exe"),
		RelaunchExecutablePath:   filepath.Join(rootDir, "NeoTTS.exe"),
		RelaunchWorkingDirectory: rootDir,
	}

	var launchCalls []ProcessLaunchSpec
	err := ExecutePlan(
		ExecutePlanOptions{
			PlanPath:              planPath,
			BootstrapPID:          3456,
			CurrentPID:            4567,
			CurrentExecutablePath: plan.UpdateAgentTargetPath,
			WaitTimeout:           5 * time.Second,
		},
		plan,
		ExecutePlanDeps{
			WaitForProcessExit: func(pid int, timeout time.Duration) error { return nil },
			ReplaceFile:        func(sourcePath string, targetPath string) error { return nil },
			StartProcess: func(spec ProcessLaunchSpec) error {
				launchCalls = append(launchCalls, spec)
				return nil
			},
		},
	)
	if err != nil {
		t.Fatalf("ExecutePlan returned error: %v", err)
	}

	if len(launchCalls) != 1 {
		t.Fatalf("launch calls = %d, want 1", len(launchCalls))
	}
	if launchCalls[0].ExecutablePath != plan.UpdateAgentSourcePath {
		t.Fatalf("second hop executable = %q, want %q", launchCalls[0].ExecutablePath, plan.UpdateAgentSourcePath)
	}
	if launchCalls[0].WorkingDirectory != plan.RelaunchWorkingDirectory {
		t.Fatalf("second hop working dir = %q, want %q", launchCalls[0].WorkingDirectory, plan.RelaunchWorkingDirectory)
	}
	if len(launchCalls[0].Arguments) != 4 {
		t.Fatalf("second hop args = %#v, want 4 args", launchCalls[0].Arguments)
	}
	if launchCalls[0].Arguments[0] != "--plan" || launchCalls[0].Arguments[1] != planPath {
		t.Fatalf("second hop args = %#v, want --plan %q", launchCalls[0].Arguments, planPath)
	}
	if launchCalls[0].Arguments[2] != "--bootstrap-pid" || launchCalls[0].Arguments[3] != "4567" {
		t.Fatalf("second hop args = %#v, want bootstrap-pid 4567", launchCalls[0].Arguments)
	}
}

func TestExecutePlanReplacesUpdateAgentOnSecondHopBeforeRelaunch(t *testing.T) {
	plan := Plan{
		SchemaVersion:            1,
		BootstrapSourcePath:      `F:\NeoTTS\packages\bootstrap\1.2.0\NeoTTS.exe`,
		BootstrapTargetPath:      `F:\NeoTTS\NeoTTS.exe`,
		UpdateAgentSourcePath:    `F:\NeoTTS\packages\update-agent\1.2.0\NeoTTSUpdateAgent.exe`,
		UpdateAgentTargetPath:    `F:\NeoTTS\NeoTTSUpdateAgent.exe`,
		RelaunchExecutablePath:   `F:\NeoTTS\NeoTTS.exe`,
		RelaunchWorkingDirectory: `F:\NeoTTS`,
	}

	var replaced [][2]string
	var launched ProcessLaunchSpec
	err := ExecutePlan(
		ExecutePlanOptions{
			PlanPath:              `F:\NeoTTS\agent-plan.json`,
			BootstrapPID:          3456,
			CurrentPID:            4567,
			CurrentExecutablePath: plan.UpdateAgentSourcePath,
			WaitTimeout:           5 * time.Second,
		},
		plan,
		ExecutePlanDeps{
			WaitForProcessExit: func(pid int, timeout time.Duration) error { return nil },
			ReplaceFile: func(sourcePath string, targetPath string) error {
				replaced = append(replaced, [2]string{sourcePath, targetPath})
				return nil
			},
			StartProcess: func(spec ProcessLaunchSpec) error {
				launched = spec
				return nil
			},
		},
	)
	if err != nil {
		t.Fatalf("ExecutePlan returned error: %v", err)
	}

	if len(replaced) != 2 {
		t.Fatalf("replace calls = %d, want 2", len(replaced))
	}
	if replaced[1][0] != plan.UpdateAgentSourcePath || replaced[1][1] != plan.UpdateAgentTargetPath {
		t.Fatalf("update-agent replace = %#v, want source=%q target=%q", replaced[1], plan.UpdateAgentSourcePath, plan.UpdateAgentTargetPath)
	}
	if launched.ExecutablePath != plan.RelaunchExecutablePath {
		t.Fatalf("relaunch executable = %q, want %q", launched.ExecutablePath, plan.RelaunchExecutablePath)
	}
}

func TestExecutePlanReturnsReplaceFailure(t *testing.T) {
	plan := Plan{
		SchemaVersion:            1,
		BootstrapSourcePath:      `F:\NeoTTS\packages\bootstrap\1.2.0\NeoTTS.exe`,
		BootstrapTargetPath:      `F:\NeoTTS\NeoTTS.exe`,
		RelaunchExecutablePath:   `F:\NeoTTS\NeoTTS.exe`,
		RelaunchWorkingDirectory: `F:\NeoTTS`,
	}

	expected := errors.New("file is locked")
	err := ExecutePlan(
		ExecutePlanOptions{
			PlanPath:              `F:\NeoTTS\agent-plan.json`,
			BootstrapPID:          3456,
			CurrentPID:            4567,
			CurrentExecutablePath: `F:\NeoTTS\NeoTTSUpdateAgent.exe`,
			WaitTimeout:           5 * time.Second,
		},
		plan,
		ExecutePlanDeps{
			WaitForProcessExit: func(pid int, timeout time.Duration) error { return nil },
			ReplaceFile:        func(sourcePath string, targetPath string) error { return expected },
		},
	)
	if !errors.Is(err, expected) {
		t.Fatalf("ExecutePlan error = %v, want wrapped %v", err, expected)
	}
}
