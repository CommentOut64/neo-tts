package bootstrap

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

type ReleaseSource interface {
	Latest() ChannelLatest
	Manifest() ReleaseManifest
	ResolvePackageArchive(ctx context.Context, packageID string, remotePackage RemotePackage, targetPath string) error
}

type OfflineReleaseSourceAdapter struct {
	Source OfflineUpdateSource
}

func (source OfflineReleaseSourceAdapter) Latest() ChannelLatest {
	return source.Source.Latest
}

func (source OfflineReleaseSourceAdapter) Manifest() ReleaseManifest {
	return source.Source.Manifest
}

func (source OfflineReleaseSourceAdapter) ResolvePackageArchive(_ context.Context, packageID string, remotePackage RemotePackage, targetPath string) error {
	if !isSafeOfflinePathSegment(packageID) || !isSafeOfflinePathSegment(remotePackage.Version) {
		return NewBootstrapError(ErrCodeDownloadFailed, "offline package path is invalid", map[string]any{"packageId": packageID, "version": remotePackage.Version}, nil)
	}
	archivePath := filepath.Join(source.Source.ExtractedDir, "packages", packageID, remotePackage.Version+".zip")
	if !pathWithinRoot(archivePath, source.Source.ExtractedDir) {
		return NewBootstrapError(ErrCodeDownloadFailed, "offline package archive resolved outside source root", map[string]any{"packageId": packageID, "version": remotePackage.Version}, nil)
	}
	return copyFile(archivePath, targetPath)
}

func isSafeOfflinePathSegment(value string) bool {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" || trimmed != value {
		return false
	}
	return !strings.ContainsAny(trimmed, `/\`) && trimmed != "." && trimmed != ".."
}

func pathWithinRoot(path string, root string) bool {
	cleanPath, err := filepath.Abs(path)
	if err != nil {
		return false
	}
	cleanRoot, err := filepath.Abs(root)
	if err != nil {
		return false
	}
	relative, err := filepath.Rel(cleanRoot, cleanPath)
	if err != nil {
		return false
	}
	return relative == "." || (!strings.HasPrefix(relative, "..") && !filepath.IsAbs(relative))
}

func copyFile(sourcePath string, targetPath string) error {
	if strings.TrimSpace(sourcePath) == "" || strings.TrimSpace(targetPath) == "" {
		return fmt.Errorf("source and target paths are required")
	}
	if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
		return err
	}
	source, err := os.Open(sourcePath)
	if err != nil {
		return err
	}
	defer source.Close()
	target, err := os.OpenFile(targetPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	defer target.Close()
	_, err = io.Copy(target, source)
	return err
}
