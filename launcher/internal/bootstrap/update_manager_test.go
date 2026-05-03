package bootstrap

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestUpdateManagerStageReleaseDownloadsPackagesAndMarksStagedComplete(t *testing.T) {
	rootDir := t.TempDir()
	now := time.Date(2026, 4, 22, 9, 0, 0, 0, time.UTC)

	shellZip := mustZipArchive(t, map[string]string{
		"NeoTTSApp.exe": "shell-binary",
	})
	appCoreZip := mustZipArchive(t, map[string]string{
		"backend/app.py":           "print('ok')",
		"frontend-dist/index.html": "<html></html>",
		"config/voices.json":       "{}",
	})

	hits := make(map[string]int)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits[r.URL.Path]++
		switch r.URL.Path {
		case "/shell.zip":
			_, _ = w.Write(shellZip)
		case "/app-core.zip":
			_, _ = w.Write(appCoreZip)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Client:  server.Client(),
		Now:     func() time.Time { return now },
	})

	session, err := manager.StageRelease(context.Background(), StageReleaseRequest{
		SessionID:      "session-1",
		ReleaseID:      "v0.0.2",
		ManifestSHA256: "manifest-sha",
		TargetPackages: []string{"shell", "app-core"},
		RemotePackages: map[string]RemotePackage{
			"shell": {
				Version: "v0.0.2",
				URL:     server.URL + "/shell.zip",
				SHA256:  sha256Hex(shellZip),
			},
			"app-core": {
				Version: "v0.0.2",
				URL:     server.URL + "/app-core.zip",
				SHA256:  sha256Hex(appCoreZip),
			},
		},
	})
	if err != nil {
		t.Fatalf("StageRelease returned error: %v", err)
	}

	if session.Status != StageSessionStatusStagedComplete {
		t.Fatalf("Status = %q, want %q", session.Status, StageSessionStatusStagedComplete)
	}
	if !equalStrings(session.CompletedPackages, []string{"shell", "app-core"}) {
		t.Fatalf("CompletedPackages = %#v", session.CompletedPackages)
	}
	if session.PackageVersions["shell"] != "v0.0.2" {
		t.Fatalf("PackageVersions[shell] = %q", session.PackageVersions["shell"])
	}

	if hits["/shell.zip"] != 1 {
		t.Fatalf("shell download hits = %d, want 1", hits["/shell.zip"])
	}
	if hits["/app-core.zip"] != 1 {
		t.Fatalf("app-core download hits = %d, want 1", hits["/app-core.zip"])
	}

	if _, err := os.Stat(filepath.Join(rootDir, "packages", "shell", "v0.0.2", "NeoTTSApp.exe")); err != nil {
		t.Fatalf("shell package not staged: %v", err)
	}
	if _, err := os.Stat(filepath.Join(rootDir, "packages", "app-core", "v0.0.2", "frontend-dist", "index.html")); err != nil {
		t.Fatalf("app-core package not staged: %v", err)
	}
}

func TestStageReleaseUsesPackageArchiveResolver(t *testing.T) {
	rootDir := t.TempDir()
	shellZip := mustZipArchive(t, map[string]string{
		"NeoTTSApp.exe": "shell-binary",
	})
	archivePath := filepath.Join(rootDir, "source-shell.zip")
	if err := os.WriteFile(archivePath, shellZip, 0o644); err != nil {
		t.Fatalf("WriteFile(source archive) returned error: %v", err)
	}
	manager := NewUpdateManager(UpdateManagerOptions{RootDir: rootDir})

	_, err := manager.StageRelease(context.Background(), StageReleaseRequest{
		SessionID:      "test-session",
		ReleaseID:      "v0.0.2",
		ManifestSHA256: "manifest-sha",
		TargetPackages: []string{"shell"},
		RemotePackages: map[string]RemotePackage{
			"shell": {Version: "v0.0.2", URL: "https://example.invalid/shell.zip", SHA256: sha256Hex(shellZip)},
		},
		PackageArchiveResolver: func(_ context.Context, packageID string, remote RemotePackage, targetPath string) error {
			if packageID != "shell" || remote.Version != "v0.0.2" {
				t.Fatalf("unexpected resolver args: %s %+v", packageID, remote)
			}
			payload, err := os.ReadFile(archivePath)
			if err != nil {
				return err
			}
			if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
				return err
			}
			return os.WriteFile(targetPath, payload, 0o644)
		},
	})
	if err != nil {
		t.Fatalf("StageRelease returned error: %v", err)
	}
	if !directoryExists(filepath.Join(rootDir, "packages", "shell", "v0.0.2")) {
		t.Fatal("expected shell package to be promoted")
	}
}

func TestStageReleaseFallsBackToCopyWhenPromoteRenameFails(t *testing.T) {
	rootDir := t.TempDir()
	shellZip := mustZipArchive(t, map[string]string{
		"NeoTTSApp.exe": "shell-binary",
	})
	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Rename: func(_, _ string) error {
			return os.ErrPermission
		},
	})

	session, err := manager.StageRelease(context.Background(), StageReleaseRequest{
		SessionID:      "test-session",
		ReleaseID:      "v0.0.2",
		ManifestSHA256: "manifest-sha",
		TargetPackages: []string{"shell"},
		RemotePackages: map[string]RemotePackage{
			"shell": {Version: "v0.0.2", URL: "https://example.invalid/shell.zip", SHA256: sha256Hex(shellZip)},
		},
		PackageArchiveResolver: func(_ context.Context, _ string, _ RemotePackage, targetPath string) error {
			if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
				return err
			}
			return os.WriteFile(targetPath, shellZip, 0o644)
		},
	})
	if err != nil {
		t.Fatalf("StageRelease returned error: %v", err)
	}
	if session.Status != StageSessionStatusStagedComplete {
		t.Fatalf("Status = %q, want %q", session.Status, StageSessionStatusStagedComplete)
	}
	if !directoryExists(filepath.Join(rootDir, "packages", "shell", "v0.0.2")) {
		t.Fatal("expected shell package to be promoted by copy fallback")
	}
	if directoryExists(filepath.Join(rootDir, "cache", "staging", "v0.0.2", "work", "shell")) {
		t.Fatal("expected staging work directory to be removed after copy fallback")
	}
}

func TestUpdateManagerStageReleaseReusesCompletedPackagesFromExistingSession(t *testing.T) {
	rootDir := t.TempDir()
	now := time.Date(2026, 4, 22, 9, 30, 0, 0, time.UTC)
	store := NewStateStore(rootDir)

	if err := os.MkdirAll(filepath.Join(rootDir, "packages", "shell", "v0.0.2"), 0o755); err != nil {
		t.Fatalf("MkdirAll(shell package) returned error: %v", err)
	}
	if err := os.WriteFile(filepath.Join(rootDir, "packages", "shell", "v0.0.2", "NeoTTSApp.exe"), []byte("shell"), 0o644); err != nil {
		t.Fatalf("WriteFile(shell executable) returned error: %v", err)
	}
	if err := os.WriteFile(
		filepath.Join(rootDir, "packages", "shell", "v0.0.2", PackageIntegrityFilename),
		[]byte("{\n  \"sha256\": \"unused\"\n}\n"),
		0o644,
	); err != nil {
		t.Fatalf("WriteFile(package integrity) returned error: %v", err)
	}

	session := StageSessionState{
		SchemaVersion:     1,
		ReleaseID:         "v0.0.2",
		ManifestSha256:    "manifest-sha",
		TargetPackages:    []string{"shell", "app-core"},
		CompletedPackages: []string{"shell"},
		PackageVersions: map[string]string{
			"shell":    "v0.0.2",
			"app-core": "v0.0.2",
		},
		Status:    StageSessionStatusPartial,
		CreatedAt: now.Add(-time.Minute),
		UpdatedAt: now.Add(-time.Minute),
	}
	if _, err := store.SaveStageSession(session.ReleaseID, session); err != nil {
		t.Fatalf("SaveStageSession returned error: %v", err)
	}

	appCoreZip := mustZipArchive(t, map[string]string{
		"backend/app.py":           "print('ok')",
		"frontend-dist/index.html": "<html></html>",
		"config/voices.json":       "{}",
	})

	hits := make(map[string]int)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits[r.URL.Path]++
		switch r.URL.Path {
		case "/app-core.zip":
			_, _ = w.Write(appCoreZip)
		case "/shell.zip":
			t.Fatalf("shell package should have been reused without download")
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Client:  server.Client(),
		Now:     func() time.Time { return now },
	})

	got, err := manager.StageRelease(context.Background(), StageReleaseRequest{
		SessionID:      "session-2",
		ReleaseID:      "v0.0.2",
		ManifestSHA256: "manifest-sha",
		TargetPackages: []string{"shell", "app-core"},
		RemotePackages: map[string]RemotePackage{
			"shell": {
				Version: "v0.0.2",
				URL:     server.URL + "/shell.zip",
				SHA256:  "unused",
			},
			"app-core": {
				Version: "v0.0.2",
				URL:     server.URL + "/app-core.zip",
				SHA256:  sha256Hex(appCoreZip),
			},
		},
	})
	if err != nil {
		t.Fatalf("StageRelease returned error: %v", err)
	}

	if hits["/app-core.zip"] != 1 {
		t.Fatalf("app-core download hits = %d, want 1", hits["/app-core.zip"])
	}
	if got.Status != StageSessionStatusStagedComplete {
		t.Fatalf("Status = %q, want %q", got.Status, StageSessionStatusStagedComplete)
	}
}

func TestUpdateManagerStageReleaseKeepsPartialSessionWhenValidationFails(t *testing.T) {
	rootDir := t.TempDir()
	now := time.Date(2026, 4, 22, 10, 0, 0, 0, time.UTC)

	invalidShellZip := mustZipArchive(t, map[string]string{
		"README.txt": "missing executable",
	})

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/shell.zip" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write(invalidShellZip)
	}))
	defer server.Close()

	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Client:  server.Client(),
		Now:     func() time.Time { return now },
	})

	_, err := manager.StageRelease(context.Background(), StageReleaseRequest{
		SessionID:      "session-1",
		ReleaseID:      "v0.0.2",
		ManifestSHA256: "manifest-sha",
		TargetPackages: []string{"shell"},
		RemotePackages: map[string]RemotePackage{
			"shell": {
				Version: "v0.0.2",
				URL:     server.URL + "/shell.zip",
				SHA256:  sha256Hex(invalidShellZip),
			},
		},
	})
	if err == nil {
		t.Fatal("StageRelease returned nil error, want validation failure")
	}

	bootstrapErr, ok := err.(*BootstrapError)
	if !ok {
		t.Fatalf("error type = %T, want *BootstrapError", err)
	}
	if bootstrapErr.Code != ErrCodeStageFailed {
		t.Fatalf("Code = %q, want %q", bootstrapErr.Code, ErrCodeStageFailed)
	}

	session, loadErr := NewStateStore(rootDir).LoadStageSession("v0.0.2")
	if loadErr != nil {
		t.Fatalf("LoadStageSession returned error: %v", loadErr)
	}
	if session.Status != StageSessionStatusPartial {
		t.Fatalf("Status = %q, want %q", session.Status, StageSessionStatusPartial)
	}
	if len(session.CompletedPackages) != 0 {
		t.Fatalf("CompletedPackages = %#v, want empty", session.CompletedPackages)
	}
}

func TestUpdateManagerFindResumableStageSessionReturnsMostRecentStagedCompleteSession(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)

	older := StageSessionState{
		SchemaVersion:  1,
		ReleaseID:      "v0.0.2",
		ManifestSha256: "sha-1",
		TargetPackages: []string{"shell"},
		PackageVersions: map[string]string{
			"shell": "v0.0.2",
		},
		Status:    StageSessionStatusStagedComplete,
		CreatedAt: time.Date(2026, 4, 22, 8, 0, 0, 0, time.UTC),
		UpdatedAt: time.Date(2026, 4, 22, 8, 10, 0, 0, time.UTC),
	}
	newer := StageSessionState{
		SchemaVersion:  1,
		ReleaseID:      "v0.0.3",
		ManifestSha256: "sha-2",
		TargetPackages: []string{"shell"},
		PackageVersions: map[string]string{
			"shell": "v0.0.3",
		},
		Status:    StageSessionStatusStagedComplete,
		CreatedAt: time.Date(2026, 4, 22, 9, 0, 0, 0, time.UTC),
		UpdatedAt: time.Date(2026, 4, 22, 9, 10, 0, 0, time.UTC),
	}
	partial := StageSessionState{
		SchemaVersion:  1,
		ReleaseID:      "v0.0.4",
		ManifestSha256: "sha-3",
		TargetPackages: []string{"shell"},
		PackageVersions: map[string]string{
			"shell": "v0.0.4",
		},
		Status:    StageSessionStatusPartial,
		CreatedAt: time.Date(2026, 4, 22, 10, 0, 0, 0, time.UTC),
		UpdatedAt: time.Date(2026, 4, 22, 10, 10, 0, 0, time.UTC),
	}
	for _, session := range []StageSessionState{older, newer, partial} {
		if _, err := store.SaveStageSession(session.ReleaseID, session); err != nil {
			t.Fatalf("SaveStageSession(%s) returned error: %v", session.ReleaseID, err)
		}
	}

	manager := NewUpdateManager(UpdateManagerOptions{RootDir: rootDir})
	got, ok, err := manager.FindResumableStageSession()
	if err != nil {
		t.Fatalf("FindResumableStageSession returned error: %v", err)
	}
	if !ok {
		t.Fatal("FindResumableStageSession returned ok=false, want true")
	}
	if got.ReleaseID != "v0.0.3" {
		t.Fatalf("ReleaseID = %q, want %q", got.ReleaseID, "v0.0.3")
	}
}

func TestUpdateManagerRecoverPendingSwitchRestoresLastKnownGoodAndRecordsFailure(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)

	current := CurrentState{SchemaVersion: 1, ReleaseID: "v0.0.2"}
	lastKnownGood := CurrentState{SchemaVersion: 1, ReleaseID: "v0.0.1"}
	pending := PendingSwitchState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.2",
		CreatedAt:     time.Date(2026, 4, 22, 8, 30, 0, 0, time.UTC),
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

	now := time.Date(2026, 4, 22, 9, 0, 0, 0, time.UTC)
	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Now:     func() time.Time { return now },
	})

	recovered, err := manager.RecoverPendingSwitch()
	if err != nil {
		t.Fatalf("RecoverPendingSwitch returned error: %v", err)
	}
	if !recovered {
		t.Fatal("RecoverPendingSwitch returned false, want true")
	}

	gotCurrent, err := store.LoadCurrent()
	if err != nil {
		t.Fatalf("LoadCurrent returned error: %v", err)
	}
	if gotCurrent.ReleaseID != "v0.0.1" {
		t.Fatalf("LoadCurrent.ReleaseID = %q, want %q", gotCurrent.ReleaseID, "v0.0.1")
	}

	gotFailed, err := store.LoadFailedRelease()
	if err != nil {
		t.Fatalf("LoadFailedRelease returned error: %v", err)
	}
	if gotFailed.ReleaseID != "v0.0.2" {
		t.Fatalf("FailedRelease.ReleaseID = %q, want %q", gotFailed.ReleaseID, "v0.0.2")
	}
	if gotFailed.Code != ErrCodeSwitchFailed {
		t.Fatalf("FailedRelease.Code = %q, want %q", gotFailed.Code, ErrCodeSwitchFailed)
	}

	if _, err := os.Stat(filepath.Join(rootDir, "state", "pending-switch.json")); !os.IsNotExist(err) {
		t.Fatalf("pending-switch.json should be deleted, got err=%v", err)
	}
}

func TestUpdateManagerCleanupObsoletePackagesDeletesOnlyExpiredUnreferencedDirectories(t *testing.T) {
	rootDir := t.TempDir()
	store := NewStateStore(rootDir)

	current := CurrentState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.3",
		Packages: map[string]PackageState{
			"shell": {Version: "v0.0.3", Root: filepath.Join(rootDir, "packages", "shell", "v0.0.3")},
		},
	}
	if _, err := store.SaveCurrent(current); err != nil {
		t.Fatalf("SaveCurrent returned error: %v", err)
	}

	session := StageSessionState{
		SchemaVersion:  1,
		ReleaseID:      "v0.0.4",
		ManifestSha256: "sha",
		TargetPackages: []string{"runtime"},
		PackageVersions: map[string]string{
			"runtime": "py311-cu128-v2",
		},
		Status:    StageSessionStatusPartial,
		CreatedAt: time.Date(2026, 4, 22, 7, 0, 0, 0, time.UTC),
		UpdatedAt: time.Date(2026, 4, 22, 7, 10, 0, 0, time.UTC),
	}
	if _, err := store.SaveStageSession(session.ReleaseID, session); err != nil {
		t.Fatalf("SaveStageSession returned error: %v", err)
	}

	stalePackageDir := filepath.Join(rootDir, "packages", "app-core", "v0.0.1")
	recentPackageDir := filepath.Join(rootDir, "packages", "models", "builtin-v2")
	stagedPackageDir := filepath.Join(rootDir, "packages", "runtime", "py311-cu128-v2")
	currentPackageDir := filepath.Join(rootDir, "packages", "shell", "v0.0.3")
	for _, dir := range []string{stalePackageDir, recentPackageDir, stagedPackageDir, currentPackageDir} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatalf("MkdirAll(%s) returned error: %v", dir, err)
		}
	}
	writeBootstrapTestFile(t, filepath.Join(currentPackageDir, "NeoTTSApp.exe"), []byte("shell"))

	staleTime := time.Date(2026, 4, 12, 9, 0, 0, 0, time.UTC)
	recentTime := time.Date(2026, 4, 22, 8, 0, 0, 0, time.UTC)
	if err := os.Chtimes(stalePackageDir, staleTime, staleTime); err != nil {
		t.Fatalf("Chtimes(stalePackageDir) returned error: %v", err)
	}
	if err := os.Chtimes(recentPackageDir, recentTime, recentTime); err != nil {
		t.Fatalf("Chtimes(recentPackageDir) returned error: %v", err)
	}
	if err := os.Chtimes(stagedPackageDir, staleTime, staleTime); err != nil {
		t.Fatalf("Chtimes(stagedPackageDir) returned error: %v", err)
	}

	oldDownloadDir := filepath.Join(rootDir, "cache", "downloads", "session-old")
	newDownloadDir := filepath.Join(rootDir, "cache", "downloads", "session-new")
	for _, dir := range []string{oldDownloadDir, newDownloadDir} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatalf("MkdirAll(%s) returned error: %v", dir, err)
		}
	}
	if err := os.WriteFile(filepath.Join(oldDownloadDir, "shell.partial"), []byte("old"), 0o644); err != nil {
		t.Fatalf("WriteFile(old download) returned error: %v", err)
	}
	if err := os.WriteFile(filepath.Join(newDownloadDir, "shell.partial"), []byte("new"), 0o644); err != nil {
		t.Fatalf("WriteFile(new download) returned error: %v", err)
	}
	oldDownloadTime := time.Date(2026, 4, 21, 7, 0, 0, 0, time.UTC)
	newDownloadTime := time.Date(2026, 4, 22, 8, 30, 0, 0, time.UTC)
	if err := os.Chtimes(oldDownloadDir, oldDownloadTime, oldDownloadTime); err != nil {
		t.Fatalf("Chtimes(oldDownloadDir) returned error: %v", err)
	}
	if err := os.Chtimes(newDownloadDir, newDownloadTime, newDownloadTime); err != nil {
		t.Fatalf("Chtimes(newDownloadDir) returned error: %v", err)
	}

	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Now:     func() time.Time { return time.Date(2026, 4, 22, 9, 0, 0, 0, time.UTC) },
	})

	if err := manager.CleanupObsoletePackages(); err != nil {
		t.Fatalf("CleanupObsoletePackages returned error: %v", err)
	}

	if _, err := os.Stat(stalePackageDir); !os.IsNotExist(err) {
		t.Fatalf("stale package dir should be deleted, got err=%v", err)
	}
	if _, err := os.Stat(recentPackageDir); err != nil {
		t.Fatalf("recent package dir should be kept, got err=%v", err)
	}
	if _, err := os.Stat(stagedPackageDir); err != nil {
		t.Fatalf("staged package dir should be kept, got err=%v", err)
	}
	if _, err := os.Stat(currentPackageDir); err != nil {
		t.Fatalf("current package dir should be kept, got err=%v", err)
	}
	if _, err := os.Stat(oldDownloadDir); !os.IsNotExist(err) {
		t.Fatalf("old download dir should be deleted, got err=%v", err)
	}
	if _, err := os.Stat(newDownloadDir); err != nil {
		t.Fatalf("new download dir should be kept, got err=%v", err)
	}
}

func mustZipArchive(t *testing.T, files map[string]string) []byte {
	t.Helper()

	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	for name, content := range files {
		entry, err := writer.Create(name)
		if err != nil {
			t.Fatalf("Create(%s) returned error: %v", name, err)
		}
		if _, err := entry.Write([]byte(content)); err != nil {
			t.Fatalf("Write(%s) returned error: %v", name, err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatalf("zip writer Close returned error: %v", err)
	}
	return buffer.Bytes()
}

func TestUpdateManagerJSONRoundTripFixture(t *testing.T) {
	payload := StageSessionState{
		SchemaVersion:     1,
		ReleaseID:         "v0.0.9",
		ManifestSha256:    "sha-9",
		TargetPackages:    []string{"shell"},
		CompletedPackages: []string{"shell"},
		PackageVersions: map[string]string{
			"shell": "v0.0.9",
		},
		Status:    StageSessionStatusStagedComplete,
		CreatedAt: time.Date(2026, 4, 22, 11, 0, 0, 0, time.UTC),
		UpdatedAt: time.Date(2026, 4, 22, 11, 5, 0, 0, time.UTC),
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("json.Marshal returned error: %v", err)
	}

	var decoded StageSessionState
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("json.Unmarshal returned error: %v", err)
	}
	if decoded.PackageVersions["shell"] != "v0.0.9" {
		t.Fatalf("PackageVersions[shell] = %q", decoded.PackageVersions["shell"])
	}
}

func TestUpdateManagerStageReleaseResumesExistingPartialArchive(t *testing.T) {
	rootDir := t.TempDir()
	now := time.Date(2026, 4, 22, 12, 0, 0, 0, time.UTC)

	shellZip := mustZipArchive(t, map[string]string{
		"NeoTTSApp.exe": "shell-binary",
	})
	partialDir := filepath.Join(rootDir, "cache", "downloads", "session-1")
	if err := os.MkdirAll(partialDir, 0o755); err != nil {
		t.Fatalf("MkdirAll(partialDir) returned error: %v", err)
	}
	partialPath := filepath.Join(partialDir, "shell.zip.partial")
	partialBytes := shellZip[:len(shellZip)/2]
	if err := os.WriteFile(partialPath, partialBytes, 0o644); err != nil {
		t.Fatalf("WriteFile(partialPath) returned error: %v", err)
	}

	var rangeHeader string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rangeHeader = r.Header.Get("Range")
		if rangeHeader != fmt.Sprintf("bytes=%d-", len(partialBytes)) {
			t.Fatalf("Range header = %q, want bytes=%d-", rangeHeader, len(partialBytes))
		}
		w.Header().Set("Content-Length", fmt.Sprintf("%d", len(shellZip)-len(partialBytes)))
		w.WriteHeader(http.StatusPartialContent)
		_, _ = w.Write(shellZip[len(partialBytes):])
	}))
	defer server.Close()

	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Client:  server.Client(),
		Now:     func() time.Time { return now },
	})

	session, err := manager.StageRelease(context.Background(), StageReleaseRequest{
		SessionID:      "session-1",
		ReleaseID:      "v0.0.2",
		ManifestSHA256: "manifest-sha",
		TargetPackages: []string{"shell"},
		RemotePackages: map[string]RemotePackage{
			"shell": {
				Version: "v0.0.2",
				URL:     server.URL + "/shell.zip",
				SHA256:  sha256Hex(shellZip),
			},
		},
	})
	if err != nil {
		t.Fatalf("StageRelease returned error: %v", err)
	}
	if session.Status != StageSessionStatusStagedComplete {
		t.Fatalf("Status = %q, want %q", session.Status, StageSessionStatusStagedComplete)
	}
}

func TestUpdateManagerStageReleaseRedownloadsCompletedPackageWhenStoredHashDoesNotMatch(t *testing.T) {
	rootDir := t.TempDir()
	now := time.Date(2026, 4, 22, 12, 30, 0, 0, time.UTC)
	store := NewStateStore(rootDir)

	shellRoot := filepath.Join(rootDir, "packages", "shell", "v0.0.2")
	if err := os.MkdirAll(shellRoot, 0o755); err != nil {
		t.Fatalf("MkdirAll(shellRoot) returned error: %v", err)
	}
	if err := os.WriteFile(filepath.Join(shellRoot, "NeoTTSApp.exe"), []byte("stale-shell"), 0o644); err != nil {
		t.Fatalf("WriteFile(shell executable) returned error: %v", err)
	}
	if err := os.WriteFile(filepath.Join(shellRoot, PackageIntegrityFilename), []byte("{\n  \"sha256\": \"stale\"\n}\n"), 0o644); err != nil {
		t.Fatalf("WriteFile(package integrity) returned error: %v", err)
	}

	session := StageSessionState{
		SchemaVersion:     1,
		ReleaseID:         "v0.0.2",
		ManifestSha256:    "manifest-sha",
		TargetPackages:    []string{"shell"},
		CompletedPackages: []string{"shell"},
		PackageVersions: map[string]string{
			"shell": "v0.0.2",
		},
		Status:    StageSessionStatusPartial,
		CreatedAt: now.Add(-time.Minute),
		UpdatedAt: now.Add(-time.Minute),
	}
	if _, err := store.SaveStageSession(session.ReleaseID, session); err != nil {
		t.Fatalf("SaveStageSession returned error: %v", err)
	}

	shellZip := mustZipArchive(t, map[string]string{
		"NeoTTSApp.exe": "fresh-shell",
	})
	hits := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
		_, _ = w.Write(shellZip)
	}))
	defer server.Close()

	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Client:  server.Client(),
		Now:     func() time.Time { return now },
	})

	got, err := manager.StageRelease(context.Background(), StageReleaseRequest{
		SessionID:      "session-2",
		ReleaseID:      "v0.0.2",
		ManifestSHA256: "manifest-sha",
		TargetPackages: []string{"shell"},
		RemotePackages: map[string]RemotePackage{
			"shell": {
				Version: "v0.0.2",
				URL:     server.URL + "/shell.zip",
				SHA256:  sha256Hex(shellZip),
			},
		},
	})
	if err != nil {
		t.Fatalf("StageRelease returned error: %v", err)
	}
	if got.Status != StageSessionStatusStagedComplete {
		t.Fatalf("Status = %q, want %q", got.Status, StageSessionStatusStagedComplete)
	}
	if hits != 1 {
		t.Fatalf("download hits = %d, want 1", hits)
	}
}

func TestValidateStagedPackageAcceptsPortableFirstPackageKeys(t *testing.T) {
	rootDir := t.TempDir()
	testCases := []struct {
		packageID string
		files     []string
	}{
		{
			packageID: "python-runtime",
			files: []string{
				filepath.Join("python-runtime", "python", "python.exe"),
			},
		},
		{
			packageID: "adapter-system",
			files: []string{
				filepath.Join("adapter-system", "gpt-sovits", "GPT_SoVITS", ".keep"),
			},
		},
		{
			packageID: "support-assets",
			files: []string{
				filepath.Join("support-assets", "gpt-sovits", ".keep"),
			},
		},
		{
			packageID: "seed-model-packages",
			files: []string{
				filepath.Join("seed-model-packages", "gpt-sovits", "neuro2", "neo-tts-model.json"),
			},
		},
	}

	for _, testCase := range testCases {
		t.Run(testCase.packageID, func(t *testing.T) {
			packageRoot := filepath.Join(rootDir, testCase.packageID)
			for _, relativePath := range testCase.files {
				writeBootstrapTestFile(t, filepath.Join(packageRoot, relativePath), []byte("ok"))
			}

			if err := validateStagedPackage(testCase.packageID, packageRoot); err != nil {
				t.Fatalf("validateStagedPackage(%q) returned error: %v", testCase.packageID, err)
			}
		})
	}
}

func TestUpdateManagerCleanupObsoletePackagesDoesNotDeleteUserDataDirectories(t *testing.T) {
	rootDir := t.TempDir()
	userPaths := []string{
		filepath.Join(rootDir, "data", "tts-registry"),
		filepath.Join(rootDir, "data", "exports"),
		filepath.Join(rootDir, "data", "secrets"),
	}
	for _, path := range userPaths {
		writeBootstrapTestFile(t, filepath.Join(path, ".keep"), []byte("keep"))
	}

	manager := NewUpdateManager(UpdateManagerOptions{
		RootDir: rootDir,
		Now:     func() time.Time { return time.Date(2026, 4, 22, 9, 0, 0, 0, time.UTC) },
	})

	if err := manager.CleanupObsoletePackages(); err != nil {
		t.Fatalf("CleanupObsoletePackages returned error: %v", err)
	}
	for _, path := range userPaths {
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("user data path %q should be kept, got err=%v", path, err)
		}
	}
}
