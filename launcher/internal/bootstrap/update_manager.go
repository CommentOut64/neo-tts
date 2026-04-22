package bootstrap

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	packageRetentionWindow   = 7 * 24 * time.Hour
	downloadRetentionWindow  = 24 * time.Hour
	PackageIntegrityFilename = ".neotts-package.json"
)

type StageReleaseRequest struct {
	SessionID              string
	ReleaseID              string
	ManifestSHA256         string
	NotesURL               string
	EstimatedDownloadBytes int64
	TargetPackages         []string
	RemotePackages         map[string]RemotePackage
	Progress               func(StageProgress)
}

type StageProgress struct {
	ReleaseID         string
	PackageID         string
	PackageVersion    string
	TotalPackages     int
	CompletedPackages int
	CurrentBytes      int64
	TotalBytes        int64
	Status            string
}

type UpdateManagerOptions struct {
	RootDir  string
	Store    StateStore
	Client   *http.Client
	Now      func() time.Time
	Download func(context.Context, *http.Client, string, string) error
	Extract  func(string, string) error
	Log      func(level string, message string, fields map[string]any)
}

type UpdateManager struct {
	rootDir  string
	store    StateStore
	client   *http.Client
	now      func() time.Time
	download func(context.Context, *http.Client, string, string) error
	extract  func(string, string) error
	log      func(level string, message string, fields map[string]any)
}

func NewUpdateManager(options UpdateManagerOptions) *UpdateManager {
	rootDir := filepath.Clean(options.RootDir)
	store := options.Store
	if store.rootDir == "" {
		store = NewStateStore(rootDir)
	}

	manager := &UpdateManager{
		rootDir: rootDir,
		store:   store,
		client:  options.Client,
		now:     options.Now,
	}
	if manager.client == nil {
		manager.client = http.DefaultClient
	}
	if manager.now == nil {
		manager.now = time.Now
	}
	manager.download = options.Download
	if manager.download == nil {
		manager.download = DownloadFile
	}
	manager.extract = options.Extract
	if manager.extract == nil {
		manager.extract = ExtractZip
	}
	manager.log = options.Log
	return manager
}

func (manager *UpdateManager) StageRelease(ctx context.Context, request StageReleaseRequest) (StageSessionState, error) {
	if strings.TrimSpace(request.ReleaseID) == "" {
		return StageSessionState{}, NewBootstrapError(ErrCodeStageFailed, "release id is required", nil, nil)
	}
	if strings.TrimSpace(request.ManifestSHA256) == "" {
		return StageSessionState{}, NewBootstrapError(ErrCodeStageFailed, "manifest sha256 is required", map[string]any{"releaseId": request.ReleaseID}, nil)
	}
	if len(request.TargetPackages) == 0 {
		return StageSessionState{}, NewBootstrapError(ErrCodeStageFailed, "target packages are required", map[string]any{"releaseId": request.ReleaseID}, nil)
	}

	now := manager.now().UTC()
	session, err := manager.loadOrInitializeSession(request, now)
	if err != nil {
		return StageSessionState{}, err
	}

	lock, acquired, err := TryAcquireUpdateLock(manager.rootDir, UpdateLockMetadata{
		OwnerPID:   os.Getpid(),
		SessionID:  request.SessionID,
		Phase:      "staging",
		AcquiredAt: now,
	})
	if err != nil {
		return session, err
	}
	if !acquired {
		return session, NewBootstrapError(ErrCodePermissionDenied, "update lock is already held by another process", map[string]any{"releaseId": request.ReleaseID}, nil)
	}
	defer func() {
		if lock != nil {
			_ = lock.Close()
		}
	}()

	for _, packageID := range request.TargetPackages {
		remotePackage, ok := request.RemotePackages[packageID]
		if !ok {
			return session, manager.failStageSession(session, NewBootstrapError(
				ErrCodeStageFailed,
				"remote package metadata is missing",
				map[string]any{"releaseId": request.ReleaseID, "packageId": packageID},
				nil,
			))
		}
		if remotePackage.Version == "" {
			return session, manager.failStageSession(session, NewBootstrapError(
				ErrCodeStageFailed,
				"remote package version is required",
				map[string]any{"releaseId": request.ReleaseID, "packageId": packageID},
				nil,
			))
		}

		session.PackageVersions[packageID] = remotePackage.Version
		targetRoot := manager.packageVersionRoot(packageID, remotePackage.Version)
		if sessionMarksPackageComplete(session, packageID) && directoryExists(targetRoot) && packageIntegrityMatches(targetRoot, remotePackage.SHA256) {
			if err := validateStagedPackage(packageID, targetRoot); err != nil {
				return session, manager.failStageSession(session, NewBootstrapError(
					ErrCodeStageFailed,
					"existing package directory is invalid",
					map[string]any{"releaseId": request.ReleaseID, "packageId": packageID, "root": targetRoot},
					err,
				))
			}
			manager.emitProgress(request.Progress, StageProgress{
				ReleaseID:         request.ReleaseID,
				PackageID:         packageID,
				PackageVersion:    remotePackage.Version,
				TotalPackages:     len(request.TargetPackages),
				CompletedPackages: len(session.CompletedPackages),
				TotalBytes:        remotePackage.SizeBytes,
				Status:            "reused",
			})
			manager.logEvent("INFO", "reused staged package from existing cache", map[string]any{
				"releaseId": request.ReleaseID,
				"packageId": packageID,
				"sessionId": request.SessionID,
			})
			continue
		}

		downloadSessionID := strings.TrimSpace(request.SessionID)
		if downloadSessionID == "" {
			downloadSessionID = request.ReleaseID
		}
		archivePath := filepath.Join(manager.rootDir, "cache", "downloads", downloadSessionID, packageID+".zip.partial")
		stagingRoot := filepath.Join(manager.rootDir, "cache", "staging", request.ReleaseID, "work", packageID)

		if err := os.RemoveAll(stagingRoot); err != nil {
			return session, manager.failStageSession(session, err)
		}
		manager.emitProgress(request.Progress, StageProgress{
			ReleaseID:         request.ReleaseID,
			PackageID:         packageID,
			PackageVersion:    remotePackage.Version,
			TotalPackages:     len(request.TargetPackages),
			CompletedPackages: len(session.CompletedPackages),
			TotalBytes:        remotePackage.SizeBytes,
			Status:            "downloading",
		})
		manager.logEvent("INFO", "starting package download", map[string]any{
			"releaseId":  request.ReleaseID,
			"packageId":  packageID,
			"sessionId":  request.SessionID,
			"packageUrl": remotePackage.URL,
		})

		if err := manager.download(ctx, manager.client, remotePackage.URL, archivePath); err != nil {
			manager.logEvent("ERROR", "package download failed", map[string]any{
				"releaseId": request.ReleaseID,
				"packageId": packageID,
				"sessionId": request.SessionID,
				"errorCode": ErrCodeDownloadFailed,
				"error":     err.Error(),
			})
			return session, manager.failStageSession(session, err)
		}
		if err := verifyFileSHA256(archivePath, remotePackage.SHA256); err != nil {
			_ = deletePathIfExists(archivePath)
			manager.logEvent("ERROR", "package sha256 mismatch", map[string]any{
				"releaseId": request.ReleaseID,
				"packageId": packageID,
				"sessionId": request.SessionID,
				"errorCode": ErrCodePackageIntegrityFailed,
				"error":     err.Error(),
			})
			return session, manager.failStageSession(session, NewBootstrapError(
				ErrCodePackageIntegrityFailed,
				"package sha256 mismatch",
				map[string]any{"releaseId": request.ReleaseID, "packageId": packageID},
				err,
			))
		}
		if err := manager.extract(archivePath, stagingRoot); err != nil {
			_ = deletePathIfExists(archivePath)
			_ = os.RemoveAll(stagingRoot)
			manager.logEvent("ERROR", "failed to extract package archive", map[string]any{
				"releaseId": request.ReleaseID,
				"packageId": packageID,
				"sessionId": request.SessionID,
				"errorCode": ErrCodeStageFailed,
				"error":     err.Error(),
			})
			return session, manager.failStageSession(session, NewBootstrapError(
				ErrCodeStageFailed,
				"failed to extract package archive",
				map[string]any{"releaseId": request.ReleaseID, "packageId": packageID},
				err,
			))
		}
		if err := validateStagedPackage(packageID, stagingRoot); err != nil {
			_ = deletePathIfExists(archivePath)
			_ = os.RemoveAll(stagingRoot)
			manager.logEvent("ERROR", "staged package structure is invalid", map[string]any{
				"releaseId": request.ReleaseID,
				"packageId": packageID,
				"sessionId": request.SessionID,
				"errorCode": ErrCodeStageFailed,
				"error":     err.Error(),
			})
			return session, manager.failStageSession(session, NewBootstrapError(
				ErrCodeStageFailed,
				"staged package structure is invalid",
				map[string]any{"releaseId": request.ReleaseID, "packageId": packageID},
				err,
			))
		}

		if err := os.MkdirAll(filepath.Dir(targetRoot), 0o755); err != nil {
			_ = deletePathIfExists(archivePath)
			_ = os.RemoveAll(stagingRoot)
			return session, manager.failStageSession(session, err)
		}
		if directoryExists(targetRoot) {
			if err := os.RemoveAll(targetRoot); err != nil {
				_ = deletePathIfExists(archivePath)
				_ = os.RemoveAll(stagingRoot)
				return session, manager.failStageSession(session, err)
			}
		}
		if err := os.Rename(stagingRoot, targetRoot); err != nil {
			_ = deletePathIfExists(archivePath)
			_ = os.RemoveAll(stagingRoot)
			return session, manager.failStageSession(session, NewBootstrapError(
				ErrCodeStageFailed,
				"failed to promote staged package into version directory",
				map[string]any{"releaseId": request.ReleaseID, "packageId": packageID, "root": targetRoot},
				err,
			))
		}
		if err := writePackageIntegrity(targetRoot, PackageIntegrityState{SHA256: remotePackage.SHA256}); err != nil {
			_ = deletePathIfExists(archivePath)
			return session, manager.failStageSession(session, err)
		}

		if err := deletePathIfExists(archivePath); err != nil {
			return session, manager.failStageSession(session, err)
		}
		if err := os.RemoveAll(stagingRoot); err != nil {
			return session, manager.failStageSession(session, err)
		}

		session.CompletedPackages = appendUniqueString(session.CompletedPackages, packageID)
		session.UpdatedAt = now
		manager.emitProgress(request.Progress, StageProgress{
			ReleaseID:         request.ReleaseID,
			PackageID:         packageID,
			PackageVersion:    remotePackage.Version,
			TotalPackages:     len(request.TargetPackages),
			CompletedPackages: len(session.CompletedPackages),
			TotalBytes:        remotePackage.SizeBytes,
			Status:            "package-complete",
		})
		manager.logEvent("INFO", "package staged successfully", map[string]any{
			"releaseId": request.ReleaseID,
			"packageId": packageID,
			"sessionId": request.SessionID,
		})
		if _, err := manager.store.SaveStageSession(session.ReleaseID, session); err != nil {
			return session, err
		}
	}

	session.Status = StageSessionStatusStagedComplete
	session.UpdatedAt = now
	manager.emitProgress(request.Progress, StageProgress{
		ReleaseID:         request.ReleaseID,
		TotalPackages:     len(request.TargetPackages),
		CompletedPackages: len(session.CompletedPackages),
		Status:            StageSessionStatusStagedComplete,
	})
	if _, err := manager.store.SaveStageSession(session.ReleaseID, session); err != nil {
		return session, err
	}
	return session, nil
}

func (manager *UpdateManager) FindResumableStageSession() (StageSessionState, bool, error) {
	sessions, err := manager.store.ListStageSessions()
	if err != nil {
		return StageSessionState{}, false, err
	}

	var best StageSessionState
	found := false
	for _, session := range sessions {
		if session.Status != StageSessionStatusStagedComplete {
			continue
		}
		if !found || session.UpdatedAt.After(best.UpdatedAt) {
			best = session
			found = true
		}
	}
	return best, found, nil
}

func (manager *UpdateManager) RecoverPendingSwitch() (bool, error) {
	pending, err := manager.store.LoadPendingSwitch()
	if err != nil {
		return false, err
	}
	if pending.ReleaseID == "" {
		return false, nil
	}

	lastKnownGood, err := manager.store.LoadLastKnownGood()
	if err != nil {
		return false, err
	}
	if lastKnownGood.ReleaseID != "" {
		if _, err := manager.store.SaveCurrent(lastKnownGood); err != nil {
			return false, err
		}
	}

	if _, err := manager.store.SaveFailedRelease(FailedReleaseState{
		SchemaVersion: 1,
		ReleaseID:     pending.ReleaseID,
		Code:          ErrCodeSwitchFailed,
		Message:       "detected interrupted pending switch during bootstrap startup",
		FailedAt:      manager.now().UTC(),
	}); err != nil {
		return false, err
	}

	if err := manager.store.DeletePendingSwitch(); err != nil {
		return false, err
	}
	return true, nil
}

func (manager *UpdateManager) CleanupObsoletePackages() error {
	referencedRoots, err := manager.referencedPackageRoots()
	if err != nil {
		return err
	}

	var cleanupErr error
	packagePattern := filepath.Join(manager.rootDir, "packages", "*", "*")
	packageDirs, err := filepath.Glob(packagePattern)
	if err != nil {
		return err
	}

	now := manager.now().UTC()
	for _, path := range packageDirs {
		info, err := os.Stat(path)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			cleanupErr = errors.Join(cleanupErr, err)
			continue
		}
		if !info.IsDir() {
			continue
		}
		if _, keep := referencedRoots[filepath.Clean(path)]; keep {
			continue
		}
		if now.Sub(info.ModTime()) < packageRetentionWindow {
			continue
		}
		if err := os.RemoveAll(path); err != nil {
			cleanupErr = errors.Join(cleanupErr, err)
		}
	}

	downloadPattern := filepath.Join(manager.rootDir, "cache", "downloads", "*")
	downloadEntries, err := filepath.Glob(downloadPattern)
	if err != nil {
		return errors.Join(cleanupErr, err)
	}
	for _, path := range downloadEntries {
		info, err := os.Stat(path)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			cleanupErr = errors.Join(cleanupErr, err)
			continue
		}
		if now.Sub(info.ModTime()) < downloadRetentionWindow {
			continue
		}
		if err := os.RemoveAll(path); err != nil {
			cleanupErr = errors.Join(cleanupErr, err)
		}
	}

	return cleanupErr
}

func (manager *UpdateManager) referencedPackageRoots() (map[string]struct{}, error) {
	referenced := make(map[string]struct{})

	for _, loader := range []func() (CurrentState, error){
		manager.store.LoadCurrent,
		manager.store.LoadLastKnownGood,
	} {
		state, err := loader()
		if err != nil {
			return nil, err
		}
		addCurrentStatePackageRoots(referenced, manager.rootDir, state)
	}

	pending, err := manager.store.LoadPendingSwitch()
	if err != nil {
		return nil, err
	}
	addPendingStatePackageRoots(referenced, manager.rootDir, pending)

	sessions, err := manager.store.ListStageSessions()
	if err != nil {
		return nil, err
	}
	for _, session := range sessions {
		if session.Status != StageSessionStatusPartial && session.Status != StageSessionStatusStagedComplete {
			continue
		}
		for packageID, version := range session.PackageVersions {
			if strings.TrimSpace(version) == "" {
				continue
			}
			referenced[manager.packageVersionRoot(packageID, version)] = struct{}{}
		}
	}
	return referenced, nil
}

func (manager *UpdateManager) loadOrInitializeSession(request StageReleaseRequest, now time.Time) (StageSessionState, error) {
	session, err := manager.store.LoadStageSession(request.ReleaseID)
	if err != nil {
		return StageSessionState{}, err
	}

	if session.ReleaseID == "" || session.ManifestSha256 != request.ManifestSHA256 {
		session = StageSessionState{
			SchemaVersion:          1,
			ReleaseID:              request.ReleaseID,
			ManifestSha256:         request.ManifestSHA256,
			TargetPackages:         append([]string(nil), request.TargetPackages...),
			PackageVersions:        make(map[string]string, len(request.RemotePackages)),
			NotesURL:               request.NotesURL,
			EstimatedDownloadBytes: request.EstimatedDownloadBytes,
			Status:                 StageSessionStatusPartial,
			CreatedAt:              now,
			UpdatedAt:              now,
		}
	} else {
		session.TargetPackages = append([]string(nil), request.TargetPackages...)
		session.NotesURL = request.NotesURL
		session.EstimatedDownloadBytes = request.EstimatedDownloadBytes
		session.Status = StageSessionStatusPartial
		session.UpdatedAt = now
		if session.PackageVersions == nil {
			session.PackageVersions = make(map[string]string, len(request.RemotePackages))
		}
	}

	for packageID, remotePackage := range request.RemotePackages {
		if strings.TrimSpace(remotePackage.Version) == "" {
			continue
		}
		session.PackageVersions[packageID] = remotePackage.Version
	}

	if _, err := manager.store.SaveStageSession(session.ReleaseID, session); err != nil {
		return StageSessionState{}, err
	}
	return session, nil
}

func (manager *UpdateManager) failStageSession(session StageSessionState, err error) error {
	session.Status = StageSessionStatusPartial
	session.UpdatedAt = manager.now().UTC()
	if _, saveErr := manager.store.SaveStageSession(session.ReleaseID, session); saveErr != nil {
		return errors.Join(err, saveErr)
	}
	return err
}

func (manager *UpdateManager) packageVersionRoot(packageID string, version string) string {
	return filepath.Clean(filepath.Join(manager.rootDir, "packages", packageID, version))
}

func verifyFileSHA256(path string, expected string) error {
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()

	hasher := sha256.New()
	if _, err := io.Copy(hasher, file); err != nil {
		return err
	}
	actual := hex.EncodeToString(hasher.Sum(nil))
	if !strings.EqualFold(actual, strings.TrimSpace(expected)) {
		return fmt.Errorf("sha256 mismatch: got %s want %s", actual, expected)
	}
	return nil
}

func validateStagedPackage(packageID string, root string) error {
	requiredPaths := map[string][]string{
		"bootstrap":         {"NeoTTS.exe"},
		"update-agent":      {"NeoTTSUpdateAgent.exe"},
		"shell":             {"NeoTTSApp.exe"},
		"app-core":          {"backend", filepath.Join("frontend-dist", "index.html"), "config"},
		"runtime":           {filepath.Join("runtime", "python", "python.exe")},
		"models":            {},
		"pretrained-models": {},
	}

	paths, ok := requiredPaths[packageID]
	if !ok {
		return fmt.Errorf("unsupported package id %q", packageID)
	}
	if len(paths) == 0 {
		entries, err := os.ReadDir(root)
		if err != nil {
			return err
		}
		if len(entries) == 0 {
			return fmt.Errorf("package root is empty")
		}
		return nil
	}

	for _, relativePath := range paths {
		if _, err := os.Stat(filepath.Join(root, relativePath)); err != nil {
			return err
		}
	}
	return nil
}

func addCurrentStatePackageRoots(target map[string]struct{}, rootDir string, state CurrentState) {
	for packageID, packageState := range state.Packages {
		root := strings.TrimSpace(packageState.Root)
		if root == "" && strings.TrimSpace(packageState.Version) != "" {
			root = filepath.Join(rootDir, "packages", packageID, packageState.Version)
		}
		if root == "" {
			continue
		}
		target[filepath.Clean(root)] = struct{}{}
	}
}

func addPendingStatePackageRoots(target map[string]struct{}, rootDir string, state PendingSwitchState) {
	for packageID, packageState := range state.Packages {
		root := strings.TrimSpace(packageState.Root)
		if root == "" && strings.TrimSpace(packageState.Version) != "" {
			root = filepath.Join(rootDir, "packages", packageID, packageState.Version)
		}
		if root == "" {
			continue
		}
		target[filepath.Clean(root)] = struct{}{}
	}
}

func sessionMarksPackageComplete(session StageSessionState, packageID string) bool {
	for _, completed := range session.CompletedPackages {
		if completed == packageID {
			return true
		}
	}
	return false
}

func appendUniqueString(values []string, value string) []string {
	for _, existing := range values {
		if existing == value {
			return values
		}
	}
	return append(values, value)
}

func directoryExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func deletePathIfExists(path string) error {
	err := os.Remove(path)
	if err == nil || errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return err
}

func (manager *UpdateManager) emitProgress(callback func(StageProgress), progress StageProgress) {
	if callback != nil {
		callback(progress)
	}
}

func (manager *UpdateManager) logEvent(level string, message string, fields map[string]any) {
	if manager.log != nil {
		manager.log(level, message, fields)
	}
}

func packageIntegrityMatches(root string, expectedSHA256 string) bool {
	if strings.TrimSpace(expectedSHA256) == "" {
		return false
	}
	integrity, err := loadJSON[PackageIntegrityState](filepath.Join(root, PackageIntegrityFilename))
	if err != nil {
		return false
	}
	return strings.EqualFold(strings.TrimSpace(integrity.SHA256), strings.TrimSpace(expectedSHA256))
}

func writePackageIntegrity(root string, integrity PackageIntegrityState) error {
	_, err := writeJSONAtomic(filepath.Join(root, PackageIntegrityFilename), integrity)
	return err
}
