package control

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
)

type ExitRequest struct {
	Kind        string `json:"kind"`
	Source      string `json:"source"`
	RequestedAt string `json:"requested_at"`
	LauncherPID int    `json:"launcher_pid"`
}

func ReadExitRequest(projectRoot string) (*ExitRequest, error) {
	path := exitRequestPath(projectRoot)
	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil
		}
		return nil, err
	}

	var request ExitRequest
	if err := json.Unmarshal(content, &request); err != nil {
		return nil, err
	}
	return &request, nil
}

func WriteExitRequest(projectRoot string, request ExitRequest) (string, error) {
	path := exitRequestPath(projectRoot)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", err
	}

	payload, err := json.MarshalIndent(request, "", "  ")
	if err != nil {
		return "", err
	}

	tempPath := path + ".tmp"
	if err := os.WriteFile(tempPath, payload, 0o644); err != nil {
		return "", err
	}
	if err := os.Rename(tempPath, path); err != nil {
		return "", err
	}

	return path, nil
}

func DeleteExitRequest(projectRoot string) error {
	path := exitRequestPath(projectRoot)
	err := os.Remove(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

func exitRequestPath(projectRoot string) string {
	return filepath.Join(projectRoot, "logs", "launcher", "control", "exit-request.json")
}
