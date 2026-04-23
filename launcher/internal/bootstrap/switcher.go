package bootstrap

import (
	"fmt"
	"path/filepath"
	"time"
)

type SwitcherOptions struct {
	RootDir string
	Store   StateStore
	Now     func() time.Time
}

type Switcher struct {
	rootDir string
	store   StateStore
	now     func() time.Time
}

func NewSwitcher(options SwitcherOptions) *Switcher {
	rootDir := filepath.Clean(options.RootDir)
	store := options.Store
	if store.rootDir == "" {
		store = NewStateStore(rootDir)
	}
	now := options.Now
	if now == nil {
		now = time.Now
	}
	return &Switcher{
		rootDir: rootDir,
		store:   store,
		now:     now,
	}
}

func (switcher *Switcher) PreparePendingSwitch(current CurrentState, session StageSessionState) (CurrentState, error) {
	candidate, err := switcher.BuildCandidateState(current, session)
	if err != nil {
		return CurrentState{}, err
	}

	lastKnownGood, err := switcher.store.LoadLastKnownGood()
	if err != nil {
		return CurrentState{}, err
	}
	if lastKnownGood.ReleaseID == "" {
		if _, err := switcher.store.SaveLastKnownGood(current); err != nil {
			return CurrentState{}, err
		}
	}

	pending := PendingSwitchState{
		SchemaVersion:    candidate.SchemaVersion,
		DistributionKind: candidate.DistributionKind,
		Channel:          candidate.Channel,
		ReleaseID:        candidate.ReleaseID,
		Packages:         clonePackageStates(candidate.Packages),
		Paths:            candidate.Paths,
		CreatedAt:        switcher.now().UTC(),
	}
	if _, err := switcher.store.SavePendingSwitch(pending); err != nil {
		return CurrentState{}, err
	}
	if _, err := switcher.store.SaveCurrent(candidate); err != nil {
		return CurrentState{}, err
	}
	return candidate, nil
}

func (switcher *Switcher) CommitPendingSwitch(candidate CurrentState) error {
	if _, err := switcher.store.SaveLastKnownGood(candidate); err != nil {
		return err
	}
	if err := switcher.store.DeletePendingSwitch(); err != nil {
		return err
	}
	if err := switcher.store.DeleteFailedRelease(); err != nil {
		return err
	}
	return nil
}

func (switcher *Switcher) RollbackPendingSwitch(code string, message string) error {
	pending, err := switcher.store.LoadPendingSwitch()
	if err != nil {
		return err
	}
	if pending.ReleaseID == "" {
		return fmt.Errorf("pending switch state is missing")
	}

	lastKnownGood, err := switcher.store.LoadLastKnownGood()
	if err != nil {
		return err
	}
	if lastKnownGood.ReleaseID == "" {
		return NewBootstrapError(ErrCodeRollbackFailed, "last-known-good release is missing", nil, nil)
	}
	if _, err := switcher.store.SaveCurrent(lastKnownGood); err != nil {
		return err
	}
	if _, err := switcher.store.SaveFailedRelease(FailedReleaseState{
		SchemaVersion: 1,
		ReleaseID:     pending.ReleaseID,
		Code:          code,
		Message:       message,
		FailedAt:      switcher.now().UTC(),
	}); err != nil {
		return err
	}
	return switcher.store.DeletePendingSwitch()
}

func (switcher *Switcher) BuildCandidateState(current CurrentState, session StageSessionState) (CurrentState, error) {
	if session.ReleaseID == "" {
		return CurrentState{}, fmt.Errorf("stage session release id is required")
	}

	candidate := current
	candidate.ReleaseID = session.ReleaseID
	candidate.Packages = clonePackageStates(current.Packages)
	if candidate.Packages == nil {
		candidate.Packages = make(map[string]PackageState, len(session.PackageVersions))
	}
	for packageID, version := range session.PackageVersions {
		if version == "" {
			continue
		}
		candidate.Packages[packageID] = PackageState{
			Version: version,
			Root:    filepath.Join(switcher.rootDir, "packages", packageID, version),
		}
	}
	return candidate, nil
}

func clonePackageStates(input map[string]PackageState) map[string]PackageState {
	if input == nil {
		return nil
	}
	cloned := make(map[string]PackageState, len(input))
	for key, value := range input {
		cloned[key] = value
	}
	return cloned
}
