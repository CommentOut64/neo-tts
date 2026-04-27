package bootstrap

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type OfflineUpdateCandidate struct {
	Path      string
	FileName  string
	ReleaseID string
	Version   string
	ModTime   time.Time
}

type OfflineUpdateSource struct {
	RootDir      string
	ReleaseID    string
	ArchivePath  string
	ExtractedDir string
	Latest       ChannelLatest
	Manifest     ReleaseManifest
}

type OfflineStartupOptions struct {
	RootDir string
	Current CurrentState
	Extract func(string, string) error
}

type OfflineStartupResult struct {
	Found  bool
	Source OfflineUpdateSource
}

type OfflineSwitchOptions struct {
	SessionID string
	Current   CurrentState
	Source    OfflineUpdateSource
	Manager   *UpdateManager
	Switcher  *Switcher
}

var offlineUpdatePackagePattern = regexp.MustCompile(`^NeoTTS-Update-v(\d+)\.(\d+)\.(\d+)\.zip$`)

func parseOfflineUpdatePackageName(fileName string) (OfflineUpdateCandidate, bool) {
	matches := offlineUpdatePackagePattern.FindStringSubmatch(fileName)
	if matches == nil {
		return OfflineUpdateCandidate{}, false
	}
	version := matches[1] + "." + matches[2] + "." + matches[3]
	return OfflineUpdateCandidate{
		FileName:  fileName,
		ReleaseID: "v" + version,
		Version:   version,
	}, true
}

func SelectOfflineUpdateCandidate(rootDir string, currentReleaseID string) (OfflineUpdateCandidate, bool, error) {
	entries, err := os.ReadDir(rootDir)
	if err != nil {
		return OfflineUpdateCandidate{}, false, err
	}

	var selected OfflineUpdateCandidate
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}

		candidate, ok := parseOfflineUpdatePackageName(entry.Name())
		if !ok || compareSemver(candidate.ReleaseID, currentReleaseID) <= 0 {
			continue
		}

		info, err := entry.Info()
		if err != nil {
			return OfflineUpdateCandidate{}, false, err
		}
		candidate.Path = filepath.Join(rootDir, entry.Name())
		candidate.ModTime = info.ModTime()

		if selected.ReleaseID == "" || compareOfflineCandidate(candidate, selected) > 0 {
			selected = candidate
		}
	}

	return selected, selected.ReleaseID != "", nil
}

func compareOfflineCandidate(left OfflineUpdateCandidate, right OfflineUpdateCandidate) int {
	if result := compareSemver(left.ReleaseID, right.ReleaseID); result != 0 {
		return result
	}
	if left.ModTime.After(right.ModTime) {
		return 1
	}
	if left.ModTime.Before(right.ModTime) {
		return -1
	}
	return strings.Compare(left.Path, right.Path)
}

func PrepareOfflineUpdateSource(rootDir string, candidate OfflineUpdateCandidate, extract func(string, string) error) (OfflineUpdateSource, error) {
	if extract == nil {
		extract = ExtractZip
	}
	inboxDir := filepath.Join(rootDir, "cache", "offline-update", "inbox")
	extractedDir := filepath.Join(rootDir, "cache", "offline-update", "extracted", candidate.ReleaseID)
	if err := os.MkdirAll(inboxDir, 0o755); err != nil {
		return OfflineUpdateSource{}, err
	}

	archivePath := filepath.Join(inboxDir, filepath.Base(candidate.Path))
	if err := os.Rename(candidate.Path, archivePath); err != nil {
		return OfflineUpdateSource{}, err
	}
	if err := os.RemoveAll(extractedDir); err != nil {
		_ = quarantineOfflineArchive(rootDir, archivePath, "failed")
		return OfflineUpdateSource{}, err
	}
	if err := extract(archivePath, extractedDir); err != nil {
		_ = quarantineOfflineArchive(rootDir, archivePath, "failed")
		return OfflineUpdateSource{}, err
	}

	return loadAndValidateOfflineSource(rootDir, candidate.ReleaseID, archivePath, extractedDir)
}

func PrepareOfflineUpdateForStartup(_ context.Context, options OfflineStartupOptions) (OfflineStartupResult, error) {
	if options.Current.DistributionKind != "portable" {
		return OfflineStartupResult{}, nil
	}
	if !offlinePathExists(filepath.Join(options.RootDir, "portable.flag")) {
		return OfflineStartupResult{}, nil
	}
	candidate, ok, err := SelectOfflineUpdateCandidate(options.RootDir, options.Current.ReleaseID)
	if err != nil || !ok {
		return OfflineStartupResult{}, err
	}
	source, err := PrepareOfflineUpdateSource(options.RootDir, candidate, options.Extract)
	if err != nil {
		return OfflineStartupResult{}, err
	}
	return OfflineStartupResult{Found: true, Source: source}, nil
}

func StageOfflineUpdateAndPrepareSwitch(ctx context.Context, options OfflineSwitchOptions) (CurrentState, error) {
	if options.Manager == nil {
		return CurrentState{}, NewBootstrapError(ErrCodeStageFailed, "update manager is required", nil, nil)
	}
	if options.Switcher == nil {
		return CurrentState{}, NewBootstrapError(ErrCodeSwitchFailed, "switcher is required", nil, nil)
	}
	adapter := OfflineReleaseSourceAdapter{Source: options.Source}
	manifest := adapter.Manifest()
	targetPackages := CalculateChangedPackages(options.Current, manifest, DefaultPackageOrder())
	if len(targetPackages) == 0 {
		_ = quarantineOfflineArchive(options.Source.RootDir, options.Source.ArchivePath, "failed")
		return CurrentState{}, NewBootstrapError(ErrCodeStageFailed, "offline update has no changed packages", map[string]any{"releaseId": manifest.ReleaseID}, nil)
	}

	stageSession, err := options.Manager.StageRelease(ctx, StageReleaseRequest{
		SessionID:              options.SessionID,
		ReleaseID:              manifest.ReleaseID,
		ManifestSHA256:         adapter.Latest().ManifestSHA256,
		NotesURL:               manifest.NotesURL,
		TargetPackages:         targetPackages,
		RemotePackages:         manifest.Packages,
		PackageArchiveResolver: adapter.ResolvePackageArchive,
	})
	if err != nil {
		_ = quarantineOfflineArchive(options.Source.RootDir, options.Source.ArchivePath, "failed")
		return CurrentState{}, err
	}
	candidate, err := options.Switcher.PreparePendingSwitch(options.Current, stageSession)
	if err != nil {
		_ = quarantineOfflineArchive(options.Source.RootDir, options.Source.ArchivePath, "failed")
		return CurrentState{}, err
	}
	return candidate, nil
}

func FinishOfflineUpdateSource(source OfflineUpdateSource) error {
	return deletePathIfExists(source.ArchivePath)
}

func FinishOfflineUpdateRelease(rootDir string, releaseID string) error {
	trimmedReleaseID := strings.TrimSpace(releaseID)
	if trimmedReleaseID == "" {
		return nil
	}
	return deletePathIfExists(filepath.Join(rootDir, "cache", "offline-update", "inbox", "NeoTTS-Update-"+trimmedReleaseID+".zip"))
}

func FailOfflineUpdateSource(source OfflineUpdateSource) error {
	return quarantineOfflineArchive(source.RootDir, source.ArchivePath, "failed")
}

func CalculateChangedPackages(current CurrentState, manifest ReleaseManifest, order []string) []string {
	if len(order) == 0 {
		order = DefaultPackageOrder()
	}
	changed := make([]string, 0, len(order))
	for _, packageID := range order {
		remotePackage, ok := manifest.Packages[packageID]
		if !ok {
			continue
		}
		currentPackage, ok := current.Packages[packageID]
		if ok && currentPackage.Version == remotePackage.Version {
			continue
		}
		changed = append(changed, packageID)
	}
	return changed
}

func loadAndValidateOfflineSource(rootDir string, releaseID string, archivePath string, extractedDir string) (OfflineUpdateSource, error) {
	latestPath := filepath.Join(extractedDir, "channels", "stable", "latest.json")
	latest, _, err := loadOfflineJSON[ChannelLatest](latestPath)
	if err != nil {
		_ = quarantineOfflineArchive(rootDir, archivePath, "invalid")
		return OfflineUpdateSource{}, err
	}
	if latest.ReleaseID != releaseID {
		_ = quarantineOfflineArchive(rootDir, archivePath, "invalid")
		return OfflineUpdateSource{}, NewBootstrapError(ErrCodeManifestFetchFailed, "offline latest release id does not match package name", map[string]any{"releaseId": releaseID, "latestReleaseId": latest.ReleaseID}, nil)
	}

	manifestPath := filepath.Join(extractedDir, "releases", releaseID, "manifest.json")
	manifest, manifestPayload, err := loadOfflineJSON[ReleaseManifest](manifestPath)
	if err != nil {
		_ = quarantineOfflineArchive(rootDir, archivePath, "invalid")
		return OfflineUpdateSource{}, err
	}
	if manifest.ReleaseID != releaseID {
		_ = quarantineOfflineArchive(rootDir, archivePath, "invalid")
		return OfflineUpdateSource{}, NewBootstrapError(ErrCodeManifestFetchFailed, "offline manifest release id does not match package name", map[string]any{"releaseId": releaseID, "manifestReleaseId": manifest.ReleaseID}, nil)
	}
	expected := strings.ToLower(strings.TrimSpace(latest.ManifestSHA256))
	if expected == "" {
		_ = quarantineOfflineArchive(rootDir, archivePath, "invalid")
		return OfflineUpdateSource{}, NewBootstrapError(ErrCodeManifestIntegrityFailed, "offline manifest sha256 is required", map[string]any{"releaseId": releaseID}, nil)
	}
	if sha256HexString(manifestPayload) != expected {
		_ = quarantineOfflineArchive(rootDir, archivePath, "invalid")
		return OfflineUpdateSource{}, NewBootstrapError(ErrCodeManifestIntegrityFailed, "offline manifest sha256 mismatch", map[string]any{"releaseId": releaseID}, nil)
	}

	return OfflineUpdateSource{
		RootDir:      rootDir,
		ReleaseID:    releaseID,
		ArchivePath:  archivePath,
		ExtractedDir: extractedDir,
		Latest:       latest,
		Manifest:     manifest,
	}, nil
}

func loadOfflineJSON[T any](path string) (T, []byte, error) {
	var value T
	file, err := os.Open(path)
	if err != nil {
		return value, nil, err
	}
	defer file.Close()

	payload, err := io.ReadAll(file)
	if err != nil {
		return value, nil, err
	}
	decoder := json.NewDecoder(strings.NewReader(string(payload)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return value, nil, fmt.Errorf("decode %s: %w", path, err)
	}
	return value, payload, nil
}

func quarantineOfflineArchive(rootDir string, archivePath string, bucket string) error {
	if archivePath == "" || !offlinePathExists(archivePath) {
		return nil
	}
	targetDir := filepath.Join(rootDir, "cache", "offline-update", bucket)
	if err := os.MkdirAll(targetDir, 0o755); err != nil {
		return err
	}
	targetPath := filepath.Join(targetDir, filepath.Base(archivePath))
	_ = os.Remove(targetPath)
	return os.Rename(archivePath, targetPath)
}

func offlinePathExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
