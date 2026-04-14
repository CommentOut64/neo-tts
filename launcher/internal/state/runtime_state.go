package state

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
)

type RuntimeState struct {
	LauncherPID   int               `json:"launcherPid"`
	RuntimeMode   string            `json:"runtimeMode"`
	FrontendMode  string            `json:"frontendMode"`
	StartupSource string            `json:"startupSource"`
	IsElevated    bool              `json:"isElevated"`
	Backend       BackendState      `json:"backend"`
	FrontendHost  FrontendHostState `json:"frontendHost"`
	LastPhase     string            `json:"lastPhase"`
	LastError     string            `json:"lastError"`
	LogFilePath   string            `json:"logFilePath"`
}

type BackendState struct {
	Mode    string `json:"mode"`
	PID     int    `json:"pid"`
	Port    int    `json:"port"`
	Origin  string `json:"origin"`
	Command string `json:"command"`
}

type FrontendHostState struct {
	Kind          string `json:"kind"`
	PID           int    `json:"pid"`
	Port          int    `json:"port"`
	Origin        string `json:"origin"`
	Command       string `json:"command"`
	BrowserOpened bool   `json:"browserOpened"`
}

func Load(projectRoot string) (RuntimeState, error) {
	path := runtimeStatePath(projectRoot)
	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return RuntimeState{}, nil
		}
		return RuntimeState{}, err
	}

	var runtimeState RuntimeState
	if err := json.Unmarshal(content, &runtimeState); err != nil {
		return RuntimeState{}, err
	}
	return runtimeState, nil
}

func Save(projectRoot string, runtimeState RuntimeState) (string, error) {
	path := runtimeStatePath(projectRoot)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", err
	}

	payload, err := json.MarshalIndent(runtimeState, "", "  ")
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

func runtimeStatePath(projectRoot string) string {
	return filepath.Join(projectRoot, "logs", "launcher", "runtime-state.json")
}
