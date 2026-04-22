package bootstrap

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
)

func DownloadFile(ctx context.Context, client *http.Client, sourceURL string, targetPath string) error {
	if client == nil {
		client = http.DefaultClient
	}
	if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
		return err
	}

	resumeOffset := int64(0)
	if info, err := os.Stat(targetPath); err == nil {
		resumeOffset = info.Size()
	} else if !os.IsNotExist(err) {
		return err
	}

	request, err := http.NewRequestWithContext(ctx, http.MethodGet, sourceURL, nil)
	if err != nil {
		return NewBootstrapError(ErrCodeDownloadFailed, "failed to build download request", map[string]any{"url": sourceURL}, err)
	}
	if resumeOffset > 0 {
		request.Header.Set("Range", fmt.Sprintf("bytes=%d-", resumeOffset))
	}
	response, err := client.Do(request)
	if err != nil {
		return NewBootstrapError(ErrCodeDownloadFailed, "failed to download package", map[string]any{"url": sourceURL}, err)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return NewBootstrapError(ErrCodeDownloadFailed, fmt.Sprintf("download returned %d", response.StatusCode), map[string]any{"url": sourceURL}, nil)
	}

	flags := os.O_CREATE | os.O_WRONLY
	switch {
	case resumeOffset > 0 && response.StatusCode == http.StatusPartialContent:
		flags |= os.O_APPEND
	default:
		flags |= os.O_TRUNC
	}
	file, err := os.OpenFile(targetPath, flags, 0o644)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = io.Copy(file, response.Body)
	return err
}
