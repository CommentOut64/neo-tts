package bootstrap

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func TestControlServerMetaReturnsAPIVersionBootstrapVersionAndSessionID(t *testing.T) {
	app := NewApp(AppOptions{
		BootstrapVersion: "1.1.0",
		SessionID:        "session-1",
	})

	request := httptest.NewRequest(http.MethodGet, "/v1/meta", nil)
	response := httptest.NewRecorder()

	app.Handler().ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d", response.Code, http.StatusOK)
	}

	var payload MetaResponse
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		t.Fatalf("Decode(meta response) returned error: %v", err)
	}
	if payload.APIVersion != ControlAPIVersion {
		t.Fatalf("APIVersion = %q, want %q", payload.APIVersion, ControlAPIVersion)
	}
	if payload.BootstrapVersion != "1.1.0" {
		t.Fatalf("BootstrapVersion = %q, want %q", payload.BootstrapVersion, "1.1.0")
	}
	if payload.SessionID != "session-1" {
		t.Fatalf("SessionID = %q, want %q", payload.SessionID, "session-1")
	}
}

func TestControlServerCheckUpdateReturnsAvailableResultFromManifestService(t *testing.T) {
	app := NewApp(AppOptions{
		BootstrapVersion: "1.1.0",
		SessionID:        "session-1",
		CheckForUpdate: func(ctx context.Context, request CheckUpdateRequest) (CheckUpdateResponse, error) {
			if request.Channel != "stable" {
				t.Fatalf("Channel = %q, want %q", request.Channel, "stable")
			}
			return CheckUpdateResponse{
				Status:                 UpdateStatusUpdateAvailable,
				ReleaseID:              "v0.0.2",
				NotesURL:               "https://cdn.example.com/notes/v0.0.2.md",
				ChangedPackages:        []string{"shell", "app-core"},
				EstimatedDownloadBytes: 300,
			}, nil
		},
	})

	body := bytes.NewBufferString(`{"channel":"stable","automatic":false}`)
	request := httptest.NewRequest(http.MethodPost, "/v1/update/check", body)
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()

	app.Handler().ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d", response.Code, http.StatusOK)
	}

	var payload CheckUpdateResponse
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		t.Fatalf("Decode(check response) returned error: %v", err)
	}
	if payload.Status != UpdateStatusUpdateAvailable {
		t.Fatalf("Status = %q, want %q", payload.Status, UpdateStatusUpdateAvailable)
	}
	if len(payload.ChangedPackages) != 2 {
		t.Fatalf("ChangedPackages = %#v, want 2 entries", payload.ChangedPackages)
	}
}

func TestControlServerSessionReadyAndRestartForUpdateUpdateSessionStatus(t *testing.T) {
	app := NewApp(AppOptions{
		BootstrapVersion: "1.1.0",
		SessionID:        "session-1",
	})

	readyRequest := httptest.NewRequest(http.MethodPost, "/v1/session/ready", bytes.NewBufferString(`{"sessionId":"renderer-1"}`))
	readyRequest.Header.Set("Content-Type", "application/json")
	readyResponse := httptest.NewRecorder()
	app.Handler().ServeHTTP(readyResponse, readyRequest)

	if readyResponse.Code != http.StatusOK {
		t.Fatalf("ready status code = %d, want %d", readyResponse.Code, http.StatusOK)
	}
	if app.SessionStatus() != SessionStatusReady {
		t.Fatalf("SessionStatus() = %q, want %q", app.SessionStatus(), SessionStatusReady)
	}

	restartRequest := httptest.NewRequest(http.MethodPost, "/v1/session/restart-for-update", bytes.NewBufferString(`{"sessionId":"renderer-1"}`))
	restartRequest.Header.Set("Content-Type", "application/json")
	restartResponse := httptest.NewRecorder()
	app.Handler().ServeHTTP(restartResponse, restartRequest)

	if restartResponse.Code != http.StatusOK {
		t.Fatalf("restart status code = %d, want %d", restartResponse.Code, http.StatusOK)
	}
	if app.SessionStatus() != SessionStatusRestartRequested {
		t.Fatalf("SessionStatus() = %q, want %q", app.SessionStatus(), SessionStatusRestartRequested)
	}
}

func TestControlServerDownloadAndRestartDelegateToCallbacks(t *testing.T) {
	app := NewApp(AppOptions{
		BootstrapVersion: "1.1.0",
		SessionID:        "session-1",
		DownloadUpdate: func(ctx context.Context, request DownloadUpdateRequest) (DownloadUpdateResponse, error) {
			if request.ReleaseID != "v0.0.2" {
				t.Fatalf("Download releaseID = %q, want %q", request.ReleaseID, "v0.0.2")
			}
			return DownloadUpdateResponse{Status: "ready-to-restart"}, nil
		},
		RestartUpdate: func(ctx context.Context, request RestartUpdateRequest) (RestartUpdateResponse, error) {
			if request.ReleaseID != "v0.0.2" {
				t.Fatalf("Restart releaseID = %q, want %q", request.ReleaseID, "v0.0.2")
			}
			return RestartUpdateResponse{Status: "switching"}, nil
		},
	})

	downloadRequest := httptest.NewRequest(http.MethodPost, "/v1/update/download", bytes.NewBufferString(`{"releaseId":"v0.0.2"}`))
	downloadRequest.Header.Set("Content-Type", "application/json")
	downloadResponse := httptest.NewRecorder()
	app.Handler().ServeHTTP(downloadResponse, downloadRequest)
	if downloadResponse.Code != http.StatusOK {
		t.Fatalf("download status code = %d, want %d", downloadResponse.Code, http.StatusOK)
	}

	var downloadPayload DownloadUpdateResponse
	if err := json.NewDecoder(downloadResponse.Body).Decode(&downloadPayload); err != nil {
		t.Fatalf("Decode(download response) returned error: %v", err)
	}
	if downloadPayload.Status != "ready-to-restart" {
		t.Fatalf("Download status = %q, want %q", downloadPayload.Status, "ready-to-restart")
	}

	restartRequest := httptest.NewRequest(http.MethodPost, "/v1/update/restart", bytes.NewBufferString(`{"releaseId":"v0.0.2"}`))
	restartRequest.Header.Set("Content-Type", "application/json")
	restartResponse := httptest.NewRecorder()
	app.Handler().ServeHTTP(restartResponse, restartRequest)
	if restartResponse.Code != http.StatusOK {
		t.Fatalf("restart status code = %d, want %d", restartResponse.Code, http.StatusOK)
	}

	var restartPayload RestartUpdateResponse
	if err := json.NewDecoder(restartResponse.Body).Decode(&restartPayload); err != nil {
		t.Fatalf("Decode(restart response) returned error: %v", err)
	}
	if restartPayload.Status != "switching" {
		t.Fatalf("Restart status = %q, want %q", restartPayload.Status, "switching")
	}
}

func TestControlServerReturnsVersionMismatchErrorPayload(t *testing.T) {
	app := NewApp(AppOptions{
		BootstrapVersion: "1.1.0",
		SessionID:        "session-1",
		CheckForUpdate: func(ctx context.Context, request CheckUpdateRequest) (CheckUpdateResponse, error) {
			return CheckUpdateResponse{}, NewBootstrapError(
				ErrCodeAPIVersionMismatch,
				"unsupported api version",
				map[string]any{"expected": ControlAPIVersion},
				nil,
			)
		},
	})

	body := bytes.NewBufferString(`{"channel":"stable","automatic":false}`)
	request := httptest.NewRequest(http.MethodPost, "/v1/update/check", body)
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()

	app.Handler().ServeHTTP(response, request)

	if response.Code != http.StatusConflict {
		t.Fatalf("status code = %d, want %d", response.Code, http.StatusConflict)
	}

	var payload ErrorResponse
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		t.Fatalf("Decode(error response) returned error: %v", err)
	}
	if payload.Code != ErrCodeAPIVersionMismatch {
		t.Fatalf("Code = %q, want %q", payload.Code, ErrCodeAPIVersionMismatch)
	}
}

func TestControlServerCheckUpdateReturnsRecoveredReadyToRestartState(t *testing.T) {
	app := NewApp(AppOptions{
		BootstrapVersion: "1.1.0",
		SessionID:        "session-1",
		InitialUpdateState: CheckUpdateResponse{
			Status:          UpdateStatusReadyToRestart,
			ReleaseID:       "v0.0.8",
			ChangedPackages: []string{"shell", "app-core"},
			Progress: &UpdateProgress{
				TotalPackages:     2,
				CompletedPackages: 2,
			},
		},
	})

	body := bytes.NewBufferString(`{"channel":"stable","automatic":true}`)
	request := httptest.NewRequest(http.MethodPost, "/v1/update/check", body)
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()

	app.Handler().ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status code = %d, want %d", response.Code, http.StatusOK)
	}

	var payload CheckUpdateResponse
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		t.Fatalf("Decode(check response) returned error: %v", err)
	}
	if payload.Status != UpdateStatusReadyToRestart {
		t.Fatalf("Status = %q, want %q", payload.Status, UpdateStatusReadyToRestart)
	}
	if payload.ReleaseID != "v0.0.8" {
		t.Fatalf("ReleaseID = %q, want %q", payload.ReleaseID, "v0.0.8")
	}
	if payload.Progress == nil || payload.Progress.CompletedPackages != 2 {
		t.Fatalf("Progress = %#v, want completed staged progress", payload.Progress)
	}
}

func TestBuildShellLaunchSpecInjectsBootstrapAndDescriptorEnvironment(t *testing.T) {
	rootDir := t.TempDir()
	current := CurrentState{
		SchemaVersion: 1,
		ReleaseID:     "v0.0.9",
		Packages: map[string]PackageState{
			"shell": {
				Version: "v0.0.9",
				Root:    filepath.Join(rootDir, "packages", "shell", "v0.0.9"),
			},
		},
	}

	spec, err := BuildShellLaunchSpec(BuildShellLaunchSpecOptions{
		RootDir:       rootDir,
		Current:       current,
		ControlOrigin: "http://127.0.0.1:19090",
		SessionID:     "session-1",
		BaseEnv:       []string{"PATH=C:\\Windows\\System32"},
	})
	if err != nil {
		t.Fatalf("BuildShellLaunchSpec returned error: %v", err)
	}

	if spec.ExecutablePath != filepath.Join(rootDir, "packages", "shell", "v0.0.9", "NeoTTSApp.exe") {
		t.Fatalf("ExecutablePath = %q", spec.ExecutablePath)
	}
	if spec.WorkingDirectory != rootDir {
		t.Fatalf("WorkingDirectory = %q, want %q", spec.WorkingDirectory, rootDir)
	}

	env := make(map[string]string)
	for _, entry := range spec.Environment {
		parts := strings.SplitN(entry, "=", 2)
		if len(parts) == 2 {
			env[parts[0]] = parts[1]
		}
	}
	if env["NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN"] != "http://127.0.0.1:19090" {
		t.Fatalf("NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN = %q", env["NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN"])
	}
	if env["NEO_TTS_BOOTSTRAP_API_VERSION"] != ControlAPIVersion {
		t.Fatalf("NEO_TTS_BOOTSTRAP_API_VERSION = %q", env["NEO_TTS_BOOTSTRAP_API_VERSION"])
	}
	if env["NEO_TTS_RUNTIME_DESCRIPTOR"] != filepath.Join(rootDir, "state", "current.json") {
		t.Fatalf("NEO_TTS_RUNTIME_DESCRIPTOR = %q", env["NEO_TTS_RUNTIME_DESCRIPTOR"])
	}
	if env["NEO_TTS_OWNER_CONTROL_ORIGIN"] != "http://127.0.0.1:19090" {
		t.Fatalf("NEO_TTS_OWNER_CONTROL_ORIGIN = %q", env["NEO_TTS_OWNER_CONTROL_ORIGIN"])
	}
	if env["NEO_TTS_OWNER_SESSION_ID"] != "session-1" {
		t.Fatalf("NEO_TTS_OWNER_SESSION_ID = %q", env["NEO_TTS_OWNER_SESSION_ID"])
	}
}
