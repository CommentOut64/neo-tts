package bootstrap

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestBuildSelfUpdatePlanUsesCandidatePackageRoots(t *testing.T) {
	rootDir := t.TempDir()
	candidate := CurrentState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		Packages: map[string]PackageState{
			"bootstrap": {
				Version: "1.2.0",
			},
			"update-agent": {
				Version: "1.2.0",
			},
		},
	}

	plan, err := BuildSelfUpdatePlan(rootDir, candidate)
	if err != nil {
		t.Fatalf("BuildSelfUpdatePlan returned error: %v", err)
	}

	if plan.SchemaVersion != 1 {
		t.Fatalf("SchemaVersion = %d, want 1", plan.SchemaVersion)
	}
	if plan.BootstrapSourcePath != filepath.Join(rootDir, "packages", "bootstrap", "1.2.0", "NeoTTS.exe") {
		t.Fatalf("BootstrapSourcePath = %q", plan.BootstrapSourcePath)
	}
	if plan.BootstrapTargetPath != filepath.Join(rootDir, "NeoTTS.exe") {
		t.Fatalf("BootstrapTargetPath = %q", plan.BootstrapTargetPath)
	}
	if plan.UpdateAgentSourcePath != filepath.Join(rootDir, "packages", "update-agent", "1.2.0", "NeoTTSUpdateAgent.exe") {
		t.Fatalf("UpdateAgentSourcePath = %q", plan.UpdateAgentSourcePath)
	}
	if plan.UpdateAgentTargetPath != filepath.Join(rootDir, "NeoTTSUpdateAgent.exe") {
		t.Fatalf("UpdateAgentTargetPath = %q", plan.UpdateAgentTargetPath)
	}
	if plan.RelaunchExecutablePath != filepath.Join(rootDir, "NeoTTS.exe") {
		t.Fatalf("RelaunchExecutablePath = %q", plan.RelaunchExecutablePath)
	}
	if plan.RelaunchWorkingDirectory != rootDir {
		t.Fatalf("RelaunchWorkingDirectory = %q, want %q", plan.RelaunchWorkingDirectory, rootDir)
	}
}

func TestSwitcherPreparePendingSwitchInitializesLastKnownGoodOnceAndWritesCandidate(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)
	now := time.Date(2026, 4, 23, 9, 0, 0, 0, time.UTC)

	current := CurrentState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.1",
		Packages: map[string]PackageState{
			"shell":     {Version: "v0.0.1"},
			"bootstrap": {Version: "1.1.0"},
		},
	}
	if _, err := store.SaveCurrent(current); err != nil {
		t.Fatalf("SaveCurrent returned error: %v", err)
	}

	switcher := NewSwitcher(SwitcherOptions{
		RootDir: rootDir,
		Store:   store,
		Now:     func() time.Time { return now },
	})
	session := StageSessionState{
		SchemaVersion:  1,
		ReleaseID:      "v0.0.2",
		TargetPackages: []string{"shell", "bootstrap"},
		PackageVersions: map[string]string{
			"shell":     "v0.0.2",
			"bootstrap": "1.2.0",
		},
	}

	candidate, err := switcher.PreparePendingSwitch(current, session)
	if err != nil {
		t.Fatalf("PreparePendingSwitch returned error: %v", err)
	}

	if candidate.ReleaseID != "v0.0.2" {
		t.Fatalf("candidate ReleaseID = %q, want v0.0.2", candidate.ReleaseID)
	}
	if candidate.Packages["shell"].Root != filepath.Join(rootDir, "packages", "shell", "v0.0.2") {
		t.Fatalf("candidate shell root = %q", candidate.Packages["shell"].Root)
	}
	if candidate.Packages["bootstrap"].Root != filepath.Join(rootDir, "packages", "bootstrap", "1.2.0") {
		t.Fatalf("candidate bootstrap root = %q", candidate.Packages["bootstrap"].Root)
	}

	lastKnownGood, err := store.LoadLastKnownGood()
	if err != nil {
		t.Fatalf("LoadLastKnownGood returned error: %v", err)
	}
	if lastKnownGood.ReleaseID != "v0.0.1" {
		t.Fatalf("last-known-good release = %q, want v0.0.1", lastKnownGood.ReleaseID)
	}

	pending, err := store.LoadPendingSwitch()
	if err != nil {
		t.Fatalf("LoadPendingSwitch returned error: %v", err)
	}
	if pending.ReleaseID != "v0.0.2" {
		t.Fatalf("pending release = %q, want v0.0.2", pending.ReleaseID)
	}
	if !pending.CreatedAt.Equal(now) {
		t.Fatalf("pending createdAt = %s, want %s", pending.CreatedAt, now)
	}

	savedCurrent, err := store.LoadCurrent()
	if err != nil {
		t.Fatalf("LoadCurrent returned error: %v", err)
	}
	if savedCurrent.ReleaseID != "v0.0.2" {
		t.Fatalf("saved current release = %q, want v0.0.2", savedCurrent.ReleaseID)
	}
}

func TestSwitcherCommitPendingSwitchPromotesCandidateAndClearsFailureMarkers(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)
	switcher := NewSwitcher(SwitcherOptions{
		RootDir: rootDir,
		Store:   store,
		Now:     func() time.Time { return time.Date(2026, 4, 23, 10, 0, 0, 0, time.UTC) },
	})

	candidate := CurrentState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		Packages: map[string]PackageState{
			"shell": {Version: "v0.0.2"},
		},
	}
	if _, err := store.SaveCurrent(candidate); err != nil {
		t.Fatalf("SaveCurrent returned error: %v", err)
	}
	if _, err := store.SavePendingSwitch(PendingSwitchState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		CreatedAt:     time.Date(2026, 4, 23, 9, 55, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("SavePendingSwitch returned error: %v", err)
	}
	if _, err := store.SaveFailedRelease(FailedReleaseState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		Code:          ErrCodeCandidateExit,
		Message:       "old failure",
		FailedAt:      time.Date(2026, 4, 23, 9, 56, 0, 0, time.UTC),
	}); err != nil {
		t.Fatalf("SaveFailedRelease returned error: %v", err)
	}

	if err := switcher.CommitPendingSwitch(candidate); err != nil {
		t.Fatalf("CommitPendingSwitch returned error: %v", err)
	}

	lastKnownGood, err := store.LoadLastKnownGood()
	if err != nil {
		t.Fatalf("LoadLastKnownGood returned error: %v", err)
	}
	if lastKnownGood.ReleaseID != "v0.0.2" {
		t.Fatalf("last-known-good release = %q, want v0.0.2", lastKnownGood.ReleaseID)
	}
	if _, err := os.Stat(filepath.Join(rootDir, "state", "pending-switch.json")); !os.IsNotExist(err) {
		t.Fatalf("pending-switch.json should be deleted, got err=%v", err)
	}
	if _, err := os.Stat(filepath.Join(rootDir, "state", "failed-release.json")); !os.IsNotExist(err) {
		t.Fatalf("failed-release.json should be deleted, got err=%v", err)
	}
}

func TestSwitcherRollbackPendingSwitchRestoresLastKnownGoodAndRecordsFailure(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)
	now := time.Date(2026, 4, 23, 11, 0, 0, 0, time.UTC)
	switcher := NewSwitcher(SwitcherOptions{
		RootDir: rootDir,
		Store:   store,
		Now:     func() time.Time { return now },
	})

	lastKnownGood := CurrentState{SchemaVersion: 1, ReleaseID: "v0.0.1"}
	candidate := CurrentState{SchemaVersion: 1, ReleaseID: "v0.0.2"}
	if _, err := store.SaveLastKnownGood(lastKnownGood); err != nil {
		t.Fatalf("SaveLastKnownGood returned error: %v", err)
	}
	if _, err := store.SaveCurrent(candidate); err != nil {
		t.Fatalf("SaveCurrent returned error: %v", err)
	}
	if _, err := store.SavePendingSwitch(PendingSwitchState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		CreatedAt:     now.Add(-time.Minute),
	}); err != nil {
		t.Fatalf("SavePendingSwitch returned error: %v", err)
	}

	if err := switcher.RollbackPendingSwitch(ErrCodeCandidateReadyTimeout, "candidate failed before ready"); err != nil {
		t.Fatalf("RollbackPendingSwitch returned error: %v", err)
	}

	current, err := store.LoadCurrent()
	if err != nil {
		t.Fatalf("LoadCurrent returned error: %v", err)
	}
	if current.ReleaseID != "v0.0.1" {
		t.Fatalf("current release = %q, want v0.0.1", current.ReleaseID)
	}

	failed, err := store.LoadFailedRelease()
	if err != nil {
		t.Fatalf("LoadFailedRelease returned error: %v", err)
	}
	if failed.ReleaseID != "v0.0.2" {
		t.Fatalf("failed release = %q, want v0.0.2", failed.ReleaseID)
	}
	if failed.Code != ErrCodeCandidateReadyTimeout {
		t.Fatalf("failed code = %q, want %q", failed.Code, ErrCodeCandidateReadyTimeout)
	}
	if failed.Message != "candidate failed before ready" {
		t.Fatalf("failed message = %q", failed.Message)
	}
	if !failed.FailedAt.Equal(now) {
		t.Fatalf("failedAt = %s, want %s", failed.FailedAt, now)
	}
	if _, err := os.Stat(filepath.Join(rootDir, "state", "pending-switch.json")); !os.IsNotExist(err) {
		t.Fatalf("pending-switch.json should be deleted, got err=%v", err)
	}
}
