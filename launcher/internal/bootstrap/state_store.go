package bootstrap

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type PackageState struct {
	Version string `json:"version"`
	Root    string `json:"root"`
}

type RuntimePaths struct {
	UserDataRoot string `json:"userDataRoot"`
	ExportsRoot  string `json:"exportsRoot"`
}

type CurrentState struct {
	SchemaVersion    int                     `json:"schemaVersion"`
	DistributionKind string                  `json:"distributionKind,omitempty"`
	Channel          string                  `json:"channel,omitempty"`
	ReleaseID        string                  `json:"releaseId,omitempty"`
	Packages         map[string]PackageState `json:"packages,omitempty"`
	Paths            RuntimePaths            `json:"paths,omitempty"`
}

type PendingSwitchState struct {
	SchemaVersion    int                     `json:"schemaVersion"`
	DistributionKind string                  `json:"distributionKind,omitempty"`
	Channel          string                  `json:"channel,omitempty"`
	ReleaseID        string                  `json:"releaseId,omitempty"`
	Packages         map[string]PackageState `json:"packages,omitempty"`
	Paths            RuntimePaths            `json:"paths,omitempty"`
	CreatedAt        time.Time               `json:"createdAt"`
}

type FailedReleaseState struct {
	SchemaVersion int       `json:"schemaVersion"`
	ReleaseID     string    `json:"releaseId"`
	Code          string    `json:"code"`
	Message       string    `json:"message"`
	FailedAt      time.Time `json:"failedAt"`
}

type StageSessionState struct {
	SchemaVersion          int               `json:"schemaVersion"`
	ReleaseID              string            `json:"releaseId"`
	ManifestSha256         string            `json:"manifestSha256"`
	TargetPackages         []string          `json:"targetPackages,omitempty"`
	CompletedPackages      []string          `json:"completedPackages,omitempty"`
	PackageVersions        map[string]string `json:"packageVersions,omitempty"`
	NotesURL               string            `json:"notesUrl,omitempty"`
	EstimatedDownloadBytes int64             `json:"estimatedDownloadBytes,omitempty"`
	Status                 string            `json:"status"`
	CreatedAt              time.Time         `json:"createdAt"`
	UpdatedAt              time.Time         `json:"updatedAt"`
}

type PackageIntegrityState struct {
	SHA256 string `json:"sha256"`
}

const (
	StageSessionStatusPartial        = "partial"
	StageSessionStatusStagedComplete = "staged-complete"
)

type StateStore struct {
	rootDir string
}

func NewStateStore(rootDir string) StateStore {
	return StateStore{rootDir: filepath.Clean(rootDir)}
}

func (store StateStore) LoadCurrent() (CurrentState, error) {
	current, err := loadJSON[CurrentState](store.currentPath())
	if err != nil {
		fallback, ok, fallbackErr := store.loadValidatedLastKnownGood()
		if fallbackErr != nil {
			return CurrentState{}, fallbackErr
		}
		if ok {
			return fallback, nil
		}
		return CurrentState{}, err
	}

	if err := validateCurrentState(store.rootDir, current); err != nil {
		fallback, ok, fallbackErr := store.loadValidatedLastKnownGood()
		if fallbackErr != nil {
			return CurrentState{}, fallbackErr
		}
		if ok {
			return fallback, nil
		}
		return CurrentState{}, err
	}
	return current, nil
}

func (store StateStore) SaveCurrent(state CurrentState) (string, error) {
	return writeJSONAtomic(store.currentPath(), state)
}

func (store StateStore) LoadLastKnownGood() (CurrentState, error) {
	return loadJSON[CurrentState](store.lastKnownGoodPath())
}

func (store StateStore) SaveLastKnownGood(state CurrentState) (string, error) {
	return writeJSONAtomic(store.lastKnownGoodPath(), state)
}

func (store StateStore) LoadPendingSwitch() (PendingSwitchState, error) {
	return loadJSON[PendingSwitchState](store.pendingSwitchPath())
}

func (store StateStore) SavePendingSwitch(state PendingSwitchState) (string, error) {
	return writeJSONAtomic(store.pendingSwitchPath(), state)
}

func (store StateStore) LoadFailedRelease() (FailedReleaseState, error) {
	return loadJSON[FailedReleaseState](store.failedReleasePath())
}

func (store StateStore) SaveFailedRelease(state FailedReleaseState) (string, error) {
	return writeJSONAtomic(store.failedReleasePath(), state)
}

func (store StateStore) LoadStageSession(releaseID string) (StageSessionState, error) {
	return loadJSON[StageSessionState](store.stageSessionPath(releaseID))
}

func (store StateStore) SaveStageSession(releaseID string, state StageSessionState) (string, error) {
	return writeJSONAtomic(store.stageSessionPath(releaseID), state)
}

func (store StateStore) ListStageSessions() ([]StageSessionState, error) {
	pattern := filepath.Join(store.rootDir, "cache", "staging", "*", "session.json")
	paths, err := filepath.Glob(pattern)
	if err != nil {
		return nil, err
	}

	sessions := make([]StageSessionState, 0, len(paths))
	for _, path := range paths {
		session, err := loadJSON[StageSessionState](path)
		if err != nil {
			return nil, err
		}
		if session.ReleaseID == "" {
			continue
		}
		sessions = append(sessions, session)
	}
	return sessions, nil
}

func (store StateStore) DeletePendingSwitch() error {
	return deleteIfExists(store.pendingSwitchPath())
}

func (store StateStore) DeleteFailedRelease() error {
	return deleteIfExists(store.failedReleasePath())
}

func (store StateStore) UpdateLockPath() string {
	return filepath.Join(store.rootDir, "state", "update.lock")
}

func (store StateStore) currentPath() string {
	return filepath.Join(store.rootDir, "state", "current.json")
}

func (store StateStore) lastKnownGoodPath() string {
	return filepath.Join(store.rootDir, "state", "last-known-good.json")
}

func (store StateStore) pendingSwitchPath() string {
	return filepath.Join(store.rootDir, "state", "pending-switch.json")
}

func (store StateStore) failedReleasePath() string {
	return filepath.Join(store.rootDir, "state", "failed-release.json")
}

func (store StateStore) stageSessionPath(releaseID string) string {
	return filepath.Join(store.rootDir, "cache", "staging", releaseID, "session.json")
}

func loadJSON[T any](path string) (T, error) {
	var value T

	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return value, nil
		}
		return value, err
	}

	if err := json.Unmarshal(content, &value); err != nil {
		return value, err
	}
	return value, nil
}

func writeJSONAtomic(path string, payload any) (string, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", err
	}

	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(payload); err != nil {
		return "", err
	}

	tempPath := path + ".tmp"
	if err := os.WriteFile(tempPath, buffer.Bytes(), 0o644); err != nil {
		return "", err
	}
	if err := replaceFileAtomically(tempPath, path); err != nil {
		return "", err
	}
	return path, nil
}

func deleteIfExists(path string) error {
	err := os.Remove(path)
	if err == nil || errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return err
}

func (store StateStore) loadValidatedLastKnownGood() (CurrentState, bool, error) {
	lastKnownGood, err := store.LoadLastKnownGood()
	if err != nil {
		return CurrentState{}, false, err
	}
	if err := validateCurrentState(store.rootDir, lastKnownGood); err != nil {
		return CurrentState{}, false, nil
	}
	return lastKnownGood, lastKnownGood.ReleaseID != "", nil
}

func validateCurrentState(rootDir string, state CurrentState) error {
	if strings.TrimSpace(state.ReleaseID) == "" {
		return nil
	}
	for packageID, packageState := range state.Packages {
		root := strings.TrimSpace(packageState.Root)
		if root == "" && strings.TrimSpace(packageState.Version) != "" {
			root = filepath.Join(filepath.Clean(rootDir), "packages", packageID, packageState.Version)
		}
		if root == "" {
			return fmt.Errorf("package %q does not have a resolved root", packageID)
		}
		if !isValidatedPackageID(packageID) {
			continue
		}
		if err := validateStagedPackage(packageID, filepath.Clean(root)); err != nil {
			return fmt.Errorf("package %q is unavailable: %w", packageID, err)
		}
	}
	return nil
}
