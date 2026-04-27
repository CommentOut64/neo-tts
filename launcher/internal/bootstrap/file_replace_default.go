//go:build !windows

package bootstrap

import "os"

func replaceFileAtomically(sourcePath string, targetPath string) error {
	return os.Rename(sourcePath, targetPath)
}
