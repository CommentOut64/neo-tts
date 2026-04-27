package bootstrap

import (
	"archive/zip"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestParseOfflineUpdatePackageName(t *testing.T) {
	candidate, ok := parseOfflineUpdatePackageName("NeoTTS-Update-v0.1.2.zip")
	if !ok {
		t.Fatal("expected valid offline update package")
	}
	if candidate.ReleaseID != "v0.1.2" || candidate.Version != "0.1.2" {
		t.Fatalf("unexpected candidate: %+v", candidate)
	}
}

func TestParseOfflineUpdatePackageNameRejectsUnsupportedNames(t *testing.T) {
	invalid := []string{
		"NeoTTS-Update-v0.1.zip",
		"NeoTTS-Update-v0.1.2-stable.zip",
		"NeoTTS-Update-latest.zip",
		"NeoTTS-Update-v0.1.2.exe",
	}
	for _, name := range invalid {
		if _, ok := parseOfflineUpdatePackageName(name); ok {
			t.Fatalf("expected %s to be rejected", name)
		}
	}
}

func TestSelectOfflineUpdateCandidateChoosesHighestAboveCurrent(t *testing.T) {
	rootDir := t.TempDir()
	writeOfflinePackageStub(t, rootDir, "NeoTTS-Update-v0.0.2.zip")
	writeOfflinePackageStub(t, rootDir, "NeoTTS-Update-v0.1.0.zip")
	writeOfflinePackageStub(t, rootDir, "NeoTTS-Update-v0.0.3-stable.zip")

	candidate, ok, err := SelectOfflineUpdateCandidate(rootDir, "v0.0.1")
	if err != nil {
		t.Fatalf("SelectOfflineUpdateCandidate returned error: %v", err)
	}
	if !ok || candidate.ReleaseID != "v0.1.0" {
		t.Fatalf("unexpected candidate: ok=%v candidate=%+v", ok, candidate)
	}
}

func TestSelectOfflineUpdateCandidateSkipsCurrentOrOlder(t *testing.T) {
	rootDir := t.TempDir()
	writeOfflinePackageStub(t, rootDir, "NeoTTS-Update-v0.0.1.zip")
	writeOfflinePackageStub(t, rootDir, "NeoTTS-Update-v0.0.0.zip")

	_, ok, err := SelectOfflineUpdateCandidate(rootDir, "v0.0.1")
	if err != nil {
		t.Fatalf("SelectOfflineUpdateCandidate returned error: %v", err)
	}
	if ok {
		t.Fatal("expected no candidate")
	}
}

func TestPrepareOfflineUpdateSourceMovesPackageOutOfRoot(t *testing.T) {
	rootDir := t.TempDir()
	archivePath := createOfflineUpdateArchive(t, rootDir, "v0.0.2")
	candidate, ok := parseOfflineUpdatePackageName(filepath.Base(archivePath))
	if !ok {
		t.Fatal("invalid test archive name")
	}
	candidate.Path = archivePath

	source, err := PrepareOfflineUpdateSource(rootDir, candidate, ExtractZip)
	if err != nil {
		t.Fatalf("PrepareOfflineUpdateSource returned error: %v", err)
	}
	if pathExists(archivePath) {
		t.Fatal("expected root archive to be moved out of root")
	}
	if !strings.Contains(source.ArchivePath, filepath.Join("cache", "offline-update", "inbox")) {
		t.Fatalf("archive was not moved to inbox: %s", source.ArchivePath)
	}
	if source.ReleaseID != "v0.0.2" || source.Latest.ReleaseID != "v0.0.2" || source.Manifest.ReleaseID != "v0.0.2" {
		t.Fatalf("unexpected source metadata: %+v", source)
	}
}

func TestPrepareOfflineUpdateSourceQuarantinesInvalidLatestReleaseID(t *testing.T) {
	rootDir := t.TempDir()
	archivePath := createOfflineUpdateArchiveWithIDs(t, rootDir, "v0.0.2", "v0.0.3", "v0.0.3")
	candidate, ok := parseOfflineUpdatePackageName(filepath.Base(archivePath))
	if !ok {
		t.Fatal("invalid test archive name")
	}
	candidate.Path = archivePath

	_, err := PrepareOfflineUpdateSource(rootDir, candidate, ExtractZip)
	if err == nil {
		t.Fatal("expected invalid offline update error")
	}
	if !pathExists(filepath.Join(rootDir, "cache", "offline-update", "invalid", filepath.Base(archivePath))) {
		t.Fatal("expected invalid archive to be quarantined")
	}
}

func TestPrepareOfflineUpdateSourceQuarantinesInvalidManifestReleaseID(t *testing.T) {
	rootDir := t.TempDir()
	archivePath := createOfflineUpdateArchiveWithIDs(t, rootDir, "v0.0.2", "v0.0.2", "v0.0.3")
	candidate, ok := parseOfflineUpdatePackageName(filepath.Base(archivePath))
	if !ok {
		t.Fatal("invalid test archive name")
	}
	candidate.Path = archivePath

	_, err := PrepareOfflineUpdateSource(rootDir, candidate, ExtractZip)
	if err == nil {
		t.Fatal("expected invalid offline update error")
	}
	if !pathExists(filepath.Join(rootDir, "cache", "offline-update", "invalid", filepath.Base(archivePath))) {
		t.Fatal("expected invalid archive to be quarantined")
	}
}

func TestPrepareOfflineUpdateSourceRejectsMissingManifestSHA256(t *testing.T) {
	rootDir := t.TempDir()
	archivePath := createOfflineUpdateArchiveWithOptions(t, rootDir, offlineArchiveOptions{
		FileReleaseID:     "v0.0.2",
		LatestReleaseID:   "v0.0.2",
		ManifestReleaseID: "v0.0.2",
		ManifestSHA256:    "",
	})
	candidate, ok := parseOfflineUpdatePackageName(filepath.Base(archivePath))
	if !ok {
		t.Fatal("invalid test archive name")
	}
	candidate.Path = archivePath

	_, err := PrepareOfflineUpdateSource(rootDir, candidate, ExtractZip)
	if err == nil {
		t.Fatal("expected invalid offline update error")
	}
	if !pathExists(filepath.Join(rootDir, "cache", "offline-update", "invalid", filepath.Base(archivePath))) {
		t.Fatal("expected invalid archive to be quarantined")
	}
}

func TestPrepareOfflineUpdateForStartupRequiresPortableFlag(t *testing.T) {
	rootDir := t.TempDir()
	createOfflineUpdateArchive(t, rootDir, "v0.0.2")

	result, err := PrepareOfflineUpdateForStartup(context.Background(), OfflineStartupOptions{
		RootDir: rootDir,
		Current: CurrentState{ReleaseID: "v0.0.1", DistributionKind: "portable"},
	})
	if err != nil {
		t.Fatalf("PrepareOfflineUpdateForStartup returned error: %v", err)
	}
	if result.Found {
		t.Fatal("expected portable descriptor without portable.flag to skip offline update")
	}
}

func TestPrepareOfflineUpdateForStartupSkipsInstalledDistribution(t *testing.T) {
	rootDir := t.TempDir()
	writeOfflinePackageStub(t, rootDir, "NeoTTS-Update-v0.0.2.zip")
	result, err := PrepareOfflineUpdateForStartup(context.Background(), OfflineStartupOptions{
		RootDir: rootDir,
		Current: CurrentState{ReleaseID: "v0.0.1", DistributionKind: "installed"},
	})
	if err != nil {
		t.Fatalf("PrepareOfflineUpdateForStartup returned error: %v", err)
	}
	if result.Found {
		t.Fatal("expected installed distribution to skip offline update")
	}
}

func TestPrepareOfflineUpdateForStartupSkipsWhenNoCandidate(t *testing.T) {
	rootDir := t.TempDir()
	result, err := PrepareOfflineUpdateForStartup(context.Background(), OfflineStartupOptions{
		RootDir: rootDir,
		Current: CurrentState{ReleaseID: "v0.0.1", DistributionKind: "portable"},
	})
	if err != nil {
		t.Fatalf("PrepareOfflineUpdateForStartup returned error: %v", err)
	}
	if result.Found {
		t.Fatal("expected no offline update")
	}
}

func TestPrepareOfflineUpdateForStartupFindsCandidateWhenPortableFlagExists(t *testing.T) {
	rootDir := t.TempDir()
	writeFile(t, filepath.Join(rootDir, "portable.flag"), nil)
	createOfflineUpdateArchive(t, rootDir, "v0.0.2")

	result, err := PrepareOfflineUpdateForStartup(context.Background(), OfflineStartupOptions{
		RootDir: rootDir,
		Current: CurrentState{ReleaseID: "v0.0.1", DistributionKind: "portable"},
	})
	if err != nil {
		t.Fatalf("PrepareOfflineUpdateForStartup returned error: %v", err)
	}
	if !result.Found || result.Source.ReleaseID != "v0.0.2" {
		t.Fatalf("unexpected offline startup result: %+v", result)
	}
}

func TestStageOfflineUpdateAndPrepareSwitch(t *testing.T) {
	rootDir := t.TempDir()
	current := seedCurrentState(t, rootDir, "v0.0.1", "portable")
	source := createPreparedOfflineSource(t, rootDir, "v0.0.2")
	manager := NewUpdateManager(UpdateManagerOptions{RootDir: rootDir})
	switcher := NewSwitcher(SwitcherOptions{RootDir: rootDir})
	var progressEvents []StageProgress

	candidate, err := StageOfflineUpdateAndPrepareSwitch(context.Background(), OfflineSwitchOptions{
		SessionID: "test-session",
		Current:   current,
		Source:    source,
		Manager:   manager,
		Switcher:  switcher,
		Progress: func(progress StageProgress) {
			progressEvents = append(progressEvents, progress)
		},
	})
	if err != nil {
		t.Fatalf("StageOfflineUpdateAndPrepareSwitch returned error: %v", err)
	}
	if candidate.ReleaseID != "v0.0.2" {
		t.Fatalf("unexpected candidate release: %s", candidate.ReleaseID)
	}
	if !pathExists(filepath.Join(rootDir, "state", "pending-switch.json")) {
		t.Fatal("expected pending switch to be written")
	}
	if !pathExists(source.ArchivePath) {
		t.Fatal("expected inbox archive to be retained until candidate validation finishes")
	}
	if len(progressEvents) == 0 {
		t.Fatal("expected offline staging progress events")
	}
}

func TestFinishOfflineUpdateReleaseDeletesInboxArchive(t *testing.T) {
	rootDir := t.TempDir()
	archivePath := filepath.Join(rootDir, "cache", "offline-update", "inbox", "NeoTTS-Update-v0.0.2.zip")
	writeFile(t, archivePath, []byte("offline package"))

	if err := FinishOfflineUpdateRelease(rootDir, "v0.0.2"); err != nil {
		t.Fatalf("FinishOfflineUpdateRelease returned error: %v", err)
	}

	if pathExists(archivePath) {
		t.Fatal("expected inbox archive to be deleted")
	}
}

func TestStageOfflineUpdateAndPrepareSwitchQuarantinesNoChangePackage(t *testing.T) {
	rootDir := t.TempDir()
	current := seedCurrentState(t, rootDir, "v0.0.2", "portable")
	source := createPreparedOfflineSource(t, rootDir, "v0.0.2")
	manager := NewUpdateManager(UpdateManagerOptions{RootDir: rootDir})
	switcher := NewSwitcher(SwitcherOptions{RootDir: rootDir})

	_, err := StageOfflineUpdateAndPrepareSwitch(context.Background(), OfflineSwitchOptions{
		SessionID: "test-session",
		Current:   current,
		Source:    source,
		Manager:   manager,
		Switcher:  switcher,
	})
	if err == nil {
		t.Fatal("expected no-change offline update error")
	}
	if !pathExists(filepath.Join(rootDir, "cache", "offline-update", "failed", filepath.Base(source.ArchivePath))) {
		t.Fatal("expected no-change archive to be quarantined as failed")
	}
}

func TestOfflineReleaseSourceRejectsPackagePathTraversal(t *testing.T) {
	rootDir := t.TempDir()
	source := OfflineReleaseSourceAdapter{Source: OfflineUpdateSource{
		RootDir:      rootDir,
		ExtractedDir: filepath.Join(rootDir, "cache", "offline-update", "extracted", "v0.0.2"),
	}}

	err := source.ResolvePackageArchive(context.Background(), "..", RemotePackage{Version: "evil"}, filepath.Join(rootDir, "target.zip"))
	if err == nil {
		t.Fatal("expected package traversal to be rejected")
	}
}

func TestExtractZipRejectsPathTraversal(t *testing.T) {
	rootDir := t.TempDir()
	archivePath := filepath.Join(rootDir, "evil.zip")
	file, err := os.Create(archivePath)
	if err != nil {
		t.Fatalf("Create returned error: %v", err)
	}
	writer := zip.NewWriter(file)
	writeZipFile(t, writer, "../evil.txt", []byte("evil"))
	if err := writer.Close(); err != nil {
		t.Fatalf("zip Close returned error: %v", err)
	}
	if err := file.Close(); err != nil {
		t.Fatalf("file Close returned error: %v", err)
	}

	err = ExtractZip(archivePath, filepath.Join(rootDir, "target"))
	if err == nil {
		t.Fatal("expected path traversal archive to be rejected")
	}
	if pathExists(filepath.Join(rootDir, "evil.txt")) {
		t.Fatal("path traversal wrote outside target dir")
	}
}

func writeOfflinePackageStub(t *testing.T, rootDir string, fileName string) string {
	t.Helper()
	path := filepath.Join(rootDir, fileName)
	if err := os.WriteFile(path, []byte("stub"), 0o644); err != nil {
		t.Fatalf("WriteFile(%s) returned error: %v", path, err)
	}
	return path
}

func createOfflineUpdateArchive(t *testing.T, rootDir string, releaseID string) string {
	t.Helper()
	return createOfflineUpdateArchiveWithIDs(t, rootDir, releaseID, releaseID, releaseID)
}

func createOfflineUpdateArchiveWithIDs(t *testing.T, rootDir string, fileReleaseID string, latestReleaseID string, manifestReleaseID string) string {
	t.Helper()
	return createOfflineUpdateArchiveWithOptions(t, rootDir, offlineArchiveOptions{
		FileReleaseID:     fileReleaseID,
		LatestReleaseID:   latestReleaseID,
		ManifestReleaseID: manifestReleaseID,
		ManifestSHA256:    "auto",
	})
}

type offlineArchiveOptions struct {
	FileReleaseID     string
	LatestReleaseID   string
	ManifestReleaseID string
	ManifestSHA256    string
}

func createOfflineUpdateArchiveWithOptions(t *testing.T, rootDir string, options offlineArchiveOptions) string {
	t.Helper()
	manifest := ReleaseManifest{
		SchemaVersion: 1,
		ReleaseID:     options.ManifestReleaseID,
		Channel:       "stable",
		ReleaseKind:   "stable",
		Packages: map[string]RemotePackage{
			"shell": {Version: options.FileReleaseID, URL: "packages/shell/" + options.FileReleaseID + ".zip", SHA256: "unused"},
		},
	}
	manifestPayload := mustJSON(t, manifest)
	manifestSHA256 := options.ManifestSHA256
	if manifestSHA256 == "auto" {
		manifestSHA256 = sha256Hex(manifestPayload)
	}
	latest := ChannelLatest{
		SchemaVersion:       1,
		Channel:             "stable",
		EnableDevRelease:    false,
		ReleaseID:           options.LatestReleaseID,
		ReleaseKind:         "stable",
		ManifestURL:         "releases/" + options.LatestReleaseID + "/manifest.json",
		ManifestSHA256:      manifestSHA256,
		MinBootstrapVersion: "0.0.0",
		PublishedAt:         time.Date(2026, 4, 26, 0, 0, 0, 0, time.UTC),
	}
	latestPayload := mustJSON(t, latest)

	archivePath := filepath.Join(rootDir, "NeoTTS-Update-"+options.FileReleaseID+".zip")
	file, err := os.Create(archivePath)
	if err != nil {
		t.Fatalf("Create(%s) returned error: %v", archivePath, err)
	}
	writer := zip.NewWriter(file)
	writeZipFile(t, writer, "channels/stable/latest.json", latestPayload)
	writeZipFile(t, writer, "releases/"+options.FileReleaseID+"/manifest.json", manifestPayload)
	if err := writer.Close(); err != nil {
		t.Fatalf("zip Close returned error: %v", err)
	}
	if err := file.Close(); err != nil {
		t.Fatalf("archive Close returned error: %v", err)
	}
	return archivePath
}

func createPreparedOfflineSource(t *testing.T, rootDir string, releaseID string) OfflineUpdateSource {
	t.Helper()
	shellZip := mustZipArchive(t, map[string]string{"NeoTTSApp.exe": "shell-binary"})
	manifest := ReleaseManifest{
		SchemaVersion: 1,
		ReleaseID:     releaseID,
		Channel:       "stable",
		ReleaseKind:   "stable",
		Packages: map[string]RemotePackage{
			"shell": {Version: releaseID, URL: "packages/shell/" + releaseID + ".zip", SHA256: sha256Hex(shellZip)},
		},
	}
	manifestPayload := mustJSON(t, manifest)
	latest := ChannelLatest{
		SchemaVersion:       1,
		Channel:             "stable",
		EnableDevRelease:    false,
		ReleaseID:           releaseID,
		ReleaseKind:         "stable",
		ManifestURL:         "releases/" + releaseID + "/manifest.json",
		ManifestSHA256:      sha256Hex(manifestPayload),
		MinBootstrapVersion: "0.0.0",
		PublishedAt:         time.Date(2026, 4, 26, 0, 0, 0, 0, time.UTC),
	}
	extractedDir := filepath.Join(rootDir, "cache", "offline-update", "extracted", releaseID)
	archivePath := filepath.Join(rootDir, "cache", "offline-update", "inbox", "NeoTTS-Update-"+releaseID+".zip")
	writeFile(t, filepath.Join(extractedDir, "channels", "stable", "latest.json"), mustJSON(t, latest))
	writeFile(t, filepath.Join(extractedDir, "releases", releaseID, "manifest.json"), manifestPayload)
	writeFile(t, filepath.Join(extractedDir, "packages", "shell", releaseID+".zip"), shellZip)
	writeFile(t, archivePath, []byte("original archive"))
	return OfflineUpdateSource{
		RootDir:      rootDir,
		ReleaseID:    releaseID,
		ArchivePath:  archivePath,
		ExtractedDir: extractedDir,
		Latest:       latest,
		Manifest:     manifest,
	}
}

func seedCurrentState(t *testing.T, rootDir string, releaseID string, distributionKind string) CurrentState {
	t.Helper()
	current := CurrentState{
		SchemaVersion:    1,
		DistributionKind: distributionKind,
		Channel:          "stable",
		ReleaseID:        releaseID,
		Packages: map[string]PackageState{
			"shell": {Version: releaseID, Root: filepath.Join(rootDir, "packages", "shell", releaseID)},
		},
	}
	if _, err := NewStateStore(rootDir).SaveCurrent(current); err != nil {
		t.Fatalf("SaveCurrent returned error: %v", err)
	}
	return current
}

func writeFile(t *testing.T, path string, payload []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("MkdirAll(%s) returned error: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, payload, 0o644); err != nil {
		t.Fatalf("WriteFile(%s) returned error: %v", path, err)
	}
}

func writeZipFile(t *testing.T, writer *zip.Writer, name string, payload []byte) {
	t.Helper()
	entry, err := writer.Create(name)
	if err != nil {
		t.Fatalf("zip Create(%s) returned error: %v", name, err)
	}
	if _, err := entry.Write(payload); err != nil {
		t.Fatalf("zip Write(%s) returned error: %v", name, err)
	}
}

func pathExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil || !errors.Is(err, os.ErrNotExist)
}
