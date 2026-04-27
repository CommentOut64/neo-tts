package bootstrap

import (
	"archive/zip"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func ExtractZip(archivePath string, targetDir string) error {
	reader, err := zip.OpenReader(archivePath)
	if err != nil {
		return err
	}
	defer reader.Close()

	if err := os.MkdirAll(targetDir, 0o755); err != nil {
		return err
	}

	cleanTargetDir, err := filepath.Abs(targetDir)
	if err != nil {
		return err
	}

	for _, file := range reader.File {
		targetPath := filepath.Join(targetDir, file.Name)
		cleanTargetPath, err := filepath.Abs(targetPath)
		if err != nil {
			return err
		}
		relativePath, err := filepath.Rel(cleanTargetDir, cleanTargetPath)
		if err != nil {
			return err
		}
		if relativePath == ".." || strings.HasPrefix(relativePath, ".."+string(filepath.Separator)) || filepath.IsAbs(relativePath) {
			return fmt.Errorf("zip entry escapes target directory: %s", file.Name)
		}
		if file.FileInfo().IsDir() {
			if err := os.MkdirAll(targetPath, file.Mode()); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
			return err
		}
		source, err := file.Open()
		if err != nil {
			return err
		}
		target, err := os.OpenFile(targetPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, file.Mode())
		if err != nil {
			source.Close()
			return err
		}
		if _, err := io.Copy(target, source); err != nil {
			target.Close()
			source.Close()
			return err
		}
		target.Close()
		source.Close()
	}
	return nil
}
