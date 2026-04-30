package bootstrap

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestStateStoreRoundTripsAllFiles(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)

	current := CurrentState{
		SchemaVersion:    1,
		DistributionKind: "portable",
		Channel:          "stable",
		ReleaseID:        "v0.0.1",
		Packages: map[string]PackageState{
			"shell": {
				Version: "v0.0.1",
				Root:    filepath.Join(rootDir, "packages", "shell", "v0.0.1"),
			},
		},
		Paths: RuntimePaths{
			UserDataRoot: filepath.Join(rootDir, "data"),
			ExportsRoot:  filepath.Join(rootDir, "exports"),
		},
	}
	lastKnownGood := current
	lastKnownGood.ReleaseID = "v0.0.0"
	pending := PendingSwitchState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		Packages: map[string]PackageState{
			"shell": {
				Version: "v0.0.2",
				Root:    filepath.Join(rootDir, "packages", "shell", "v0.0.2"),
			},
		},
		Paths: RuntimePaths{
			UserDataRoot: filepath.Join(rootDir, "data"),
			ExportsRoot:  filepath.Join(rootDir, "exports"),
		},
		CreatedAt: time.Date(2026, 4, 21, 13, 0, 0, 0, time.UTC),
	}
	failed := FailedReleaseState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		Code:          "candidate-ready-timeout",
		Message:       "启动失败",
		FailedAt:      time.Date(2026, 4, 21, 13, 5, 0, 0, time.UTC),
	}
	session := StageSessionState{
		SchemaVersion:     1,
		ReleaseID:         "v0.0.2",
		ManifestSha256:    "abc123",
		TargetPackages:    []string{"shell", "app-core"},
		CompletedPackages: []string{"shell"},
		Status:            "partial",
		CreatedAt:         time.Date(2026, 4, 21, 13, 10, 0, 0, time.UTC),
		UpdatedAt:         time.Date(2026, 4, 21, 13, 11, 0, 0, time.UTC),
	}

	if _, err := store.SaveCurrent(current); err != nil {
		t.Fatalf("SaveCurrent returned error: %v", err)
	}
	if _, err := store.SaveLastKnownGood(lastKnownGood); err != nil {
		t.Fatalf("SaveLastKnownGood returned error: %v", err)
	}
	if _, err := store.SavePendingSwitch(pending); err != nil {
		t.Fatalf("SavePendingSwitch returned error: %v", err)
	}
	if _, err := store.SaveFailedRelease(failed); err != nil {
		t.Fatalf("SaveFailedRelease returned error: %v", err)
	}
	if _, err := store.SaveStageSession(session.ReleaseID, session); err != nil {
		t.Fatalf("SaveStageSession returned error: %v", err)
	}
	writeBootstrapTestFile(t, filepath.Join(rootDir, "packages", "shell", "v0.0.1", "NeoTTSApp.exe"), []byte("shell"))

	currentPath := filepath.Join(rootDir, "state", "current.json")
	if _, err := os.Stat(currentPath + ".tmp"); !os.IsNotExist(err) {
		t.Fatalf("temporary current state file should not remain, got err=%v", err)
	}

	if got, err := store.LoadCurrent(); err != nil {
		t.Fatalf("LoadCurrent returned error: %v", err)
	} else if !reflect.DeepEqual(got, current) {
		t.Fatalf("LoadCurrent = %#v, want %#v", got, current)
	}
	if got, err := store.LoadLastKnownGood(); err != nil {
		t.Fatalf("LoadLastKnownGood returned error: %v", err)
	} else if !reflect.DeepEqual(got, lastKnownGood) {
		t.Fatalf("LoadLastKnownGood = %#v, want %#v", got, lastKnownGood)
	}
	if got, err := store.LoadPendingSwitch(); err != nil {
		t.Fatalf("LoadPendingSwitch returned error: %v", err)
	} else if !reflect.DeepEqual(got, pending) {
		t.Fatalf("LoadPendingSwitch = %#v, want %#v", got, pending)
	}
	if got, err := store.LoadFailedRelease(); err != nil {
		t.Fatalf("LoadFailedRelease returned error: %v", err)
	} else if !reflect.DeepEqual(got, failed) {
		t.Fatalf("LoadFailedRelease = %#v, want %#v", got, failed)
	}
	if got, err := store.LoadStageSession(session.ReleaseID); err != nil {
		t.Fatalf("LoadStageSession returned error: %v", err)
	} else if !reflect.DeepEqual(got, session) {
		t.Fatalf("LoadStageSession = %#v, want %#v", got, session)
	}

	failedJSON, err := os.ReadFile(filepath.Join(rootDir, "state", "failed-release.json"))
	if err != nil {
		t.Fatalf("ReadFile failed-release.json: %v", err)
	}
	if string(failedJSON) == "" || !strings.Contains(string(failedJSON), "启动失败") {
		t.Fatalf("failed-release.json should keep UTF-8 text, got %q", string(failedJSON))
	}
}

func TestSaveCurrentReplacesExistingFileAtomically(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)

	first := CurrentState{SchemaVersion: 1, ReleaseID: "v0.0.1"}
	second := CurrentState{SchemaVersion: 1, ReleaseID: "v0.0.2"}

	if _, err := store.SaveCurrent(first); err != nil {
		t.Fatalf("SaveCurrent(first) returned error: %v", err)
	}
	if _, err := store.SaveCurrent(second); err != nil {
		t.Fatalf("SaveCurrent(second) returned error: %v", err)
	}

	got, err := store.LoadCurrent()
	if err != nil {
		t.Fatalf("LoadCurrent returned error: %v", err)
	}
	if got.ReleaseID != second.ReleaseID {
		t.Fatalf("ReleaseID = %q, want %q", got.ReleaseID, second.ReleaseID)
	}

	currentPath := filepath.Join(rootDir, "state", "current.json")
	if _, err := os.Stat(currentPath + ".tmp"); !os.IsNotExist(err) {
		t.Fatalf("temporary current state file should not remain, got err=%v", err)
	}
}

func TestLoadCurrentFallsBackToLastKnownGoodWhenCurrentJSONIsInvalid(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)
	lastKnownGood := CurrentState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.1",
		Packages: map[string]PackageState{
			"shell": {
				Root: filepath.Join(rootDir, "packages", "shell", "v0.0.1"),
			},
		},
	}

	writeBootstrapTestFile(t, filepath.Join(rootDir, "packages", "shell", "v0.0.1", "NeoTTSApp.exe"), []byte("shell"))
	if _, err := store.SaveLastKnownGood(lastKnownGood); err != nil {
		t.Fatalf("SaveLastKnownGood returned error: %v", err)
	}
	writeBootstrapTestFile(t, filepath.Join(rootDir, "state", "current.json"), []byte("{invalid-json"))

	got, err := store.LoadCurrent()
	if err != nil {
		t.Fatalf("LoadCurrent returned error: %v", err)
	}
	if got.ReleaseID != lastKnownGood.ReleaseID {
		t.Fatalf("ReleaseID = %q, want %q", got.ReleaseID, lastKnownGood.ReleaseID)
	}
}

func TestLoadCurrentFallsBackToLastKnownGoodWhenCurrentPackageIsUnavailable(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)
	current := CurrentState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		Packages: map[string]PackageState{
			"shell": {
				Root: filepath.Join(rootDir, "packages", "shell", "v0.0.2"),
			},
		},
	}
	lastKnownGood := CurrentState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.1",
		Packages: map[string]PackageState{
			"shell": {
				Root: filepath.Join(rootDir, "packages", "shell", "v0.0.1"),
			},
		},
	}

	if _, err := store.SaveCurrent(current); err != nil {
		t.Fatalf("SaveCurrent returned error: %v", err)
	}
	writeBootstrapTestFile(t, filepath.Join(rootDir, "packages", "shell", "v0.0.1", "NeoTTSApp.exe"), []byte("shell"))
	if _, err := store.SaveLastKnownGood(lastKnownGood); err != nil {
		t.Fatalf("SaveLastKnownGood returned error: %v", err)
	}

	got, err := store.LoadCurrent()
	if err != nil {
		t.Fatalf("LoadCurrent returned error: %v", err)
	}
	if got.ReleaseID != lastKnownGood.ReleaseID {
		t.Fatalf("ReleaseID = %q, want %q", got.ReleaseID, lastKnownGood.ReleaseID)
	}
}

func TestReplaceFileAtomicallyReplacesExistingTarget(t *testing.T) {
	rootDir := t.TempDir()
	targetPath := filepath.Join(rootDir, "state", "current.json")
	tempPath := targetPath + ".tmp"

	if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
		t.Fatalf("MkdirAll returned error: %v", err)
	}
	if err := os.WriteFile(targetPath, []byte("old"), 0o644); err != nil {
		t.Fatalf("WriteFile(targetPath) returned error: %v", err)
	}
	if err := os.WriteFile(tempPath, []byte("new"), 0o644); err != nil {
		t.Fatalf("WriteFile(tempPath) returned error: %v", err)
	}

	if err := replaceFileAtomically(tempPath, targetPath); err != nil {
		t.Fatalf("replaceFileAtomically returned error: %v", err)
	}

	content, err := os.ReadFile(targetPath)
	if err != nil {
		t.Fatalf("ReadFile(targetPath) returned error: %v", err)
	}
	if string(content) != "new" {
		t.Fatalf("target content = %q, want %q", string(content), "new")
	}
	if _, err := os.Stat(tempPath); !os.IsNotExist(err) {
		t.Fatalf("temporary file should not remain, got err=%v", err)
	}
}

func TestTryAcquireUpdateLockWritesDiagnosticsAndIsExclusive(t *testing.T) {
	rootDir := t.TempDir()
	acquiredAt := time.Date(2026, 4, 21, 14, 0, 0, 0, time.UTC)

	first, acquired, err := TryAcquireUpdateLock(rootDir, UpdateLockMetadata{
		OwnerPID:   1234,
		SessionID:  "session-1",
		Phase:      "staging",
		AcquiredAt: acquiredAt,
	})
	if err != nil {
		t.Fatalf("TryAcquireUpdateLock(first) returned error: %v", err)
	}
	if !acquired {
		t.Fatal("first acquired = false, want true")
	}
	defer first.Close()

	lockPath := filepath.Join(rootDir, "state", "update.lock")
	content, err := os.ReadFile(lockPath)
	if err != nil {
		t.Fatalf("ReadFile(update.lock): %v", err)
	}
	if !strings.Contains(string(content), "session-1") {
		t.Fatalf("update.lock missing session id, got %q", string(content))
	}

	second, acquired, err := TryAcquireUpdateLock(rootDir, UpdateLockMetadata{
		OwnerPID:   5678,
		SessionID:  "session-2",
		Phase:      "switching",
		AcquiredAt: acquiredAt.Add(time.Minute),
	})
	if err != nil {
		t.Fatalf("TryAcquireUpdateLock(second) returned error: %v", err)
	}
	if second != nil {
		defer second.Close()
	}
	if acquired {
		t.Fatal("second acquired = true, want false")
	}

	if err := first.Close(); err != nil {
		t.Fatalf("first.Close returned error: %v", err)
	}

	third, acquired, err := TryAcquireUpdateLock(rootDir, UpdateLockMetadata{
		OwnerPID:   91011,
		SessionID:  "session-3",
		Phase:      "cleanup",
		AcquiredAt: acquiredAt.Add(2 * time.Minute),
	})
	if err != nil {
		t.Fatalf("TryAcquireUpdateLock(third) returned error: %v", err)
	}
	if third != nil {
		defer third.Close()
	}
	if !acquired {
		t.Fatal("third acquired = false, want true")
	}
}

func writeBootstrapTestFile(t *testing.T, path string, payload []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("MkdirAll(%s) returned error: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, payload, 0o644); err != nil {
		t.Fatalf("WriteFile(%s) returned error: %v", path, err)
	}
}
