package bootstrap

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

const ControlAPIVersion = "v1"
const RuntimeDescriptorEnv = "NEO_TTS_RUNTIME_DESCRIPTOR"

type SessionStatus string

const (
	SessionStatusBooting          SessionStatus = "booting"
	SessionStatusReady            SessionStatus = "session-ready"
	SessionStatusFailed           SessionStatus = "startup-failed"
	SessionStatusRestartRequested SessionStatus = "restart-requested"
)

type UpdateProgress struct {
	TotalPackages         int    `json:"totalPackages,omitempty"`
	CompletedPackages     int    `json:"completedPackages,omitempty"`
	CurrentPackageID      string `json:"currentPackageId,omitempty"`
	CurrentPackageVersion string `json:"currentPackageVersion,omitempty"`
	CurrentPackageBytes   int64  `json:"currentPackageBytes,omitempty"`
	CurrentPackageTotal   int64  `json:"currentPackageTotal,omitempty"`
}

type AppOptions struct {
	BootstrapVersion   string
	SessionID          string
	InitialUpdateState CheckUpdateResponse
	CheckForUpdate     func(context.Context, CheckUpdateRequest) (CheckUpdateResponse, error)
	DownloadUpdate     func(context.Context, DownloadUpdateRequest) (DownloadUpdateResponse, error)
	RestartUpdate      func(context.Context, RestartUpdateRequest) (RestartUpdateResponse, error)
	OnSessionEvent     func(SessionStatus, SessionEventRequest)
}

type App struct {
	bootstrapVersion string
	sessionID        string
	checkForUpdate   func(context.Context, CheckUpdateRequest) (CheckUpdateResponse, error)
	downloadUpdate   func(context.Context, DownloadUpdateRequest) (DownloadUpdateResponse, error)
	restartUpdate    func(context.Context, RestartUpdateRequest) (RestartUpdateResponse, error)
	onSessionEvent   func(SessionStatus, SessionEventRequest)

	mu            sync.RWMutex
	sessionStatus SessionStatus
	updateState   CheckUpdateResponse
}

type MetaResponse struct {
	APIVersion       string `json:"apiVersion"`
	BootstrapVersion string `json:"bootstrapVersion"`
	SessionID        string `json:"sessionId"`
}

type ErrorResponse struct {
	Code    string         `json:"code"`
	Message string         `json:"message"`
	Details map[string]any `json:"details,omitempty"`
}

type SessionEventRequest struct {
	SessionID string `json:"sessionId"`
	Code      string `json:"code,omitempty"`
	Message   string `json:"message,omitempty"`
}

type SessionEventResponse struct {
	Status SessionStatus `json:"status"`
}

type DownloadUpdateRequest struct {
	ReleaseID string `json:"releaseId,omitempty"`
}

type DownloadUpdateResponse struct {
	Status    string          `json:"status"`
	ReleaseID string          `json:"releaseId,omitempty"`
	Progress  *UpdateProgress `json:"progress,omitempty"`
	ErrorCode string          `json:"errorCode,omitempty"`
	Message   string          `json:"message,omitempty"`
}

type RestartUpdateRequest struct {
	ReleaseID string `json:"releaseId,omitempty"`
}

type RestartUpdateResponse struct {
	Status    string `json:"status"`
	ReleaseID string `json:"releaseId,omitempty"`
}

func NewApp(options AppOptions) *App {
	initialUpdateState := options.InitialUpdateState
	if initialUpdateState.Status == "" {
		initialUpdateState = CheckUpdateResponse{Status: UpdateStatusIdle}
	}
	return &App{
		bootstrapVersion: options.BootstrapVersion,
		sessionID:        options.SessionID,
		checkForUpdate:   options.CheckForUpdate,
		downloadUpdate:   options.DownloadUpdate,
		restartUpdate:    options.RestartUpdate,
		onSessionEvent:   options.OnSessionEvent,
		sessionStatus:    SessionStatusBooting,
		updateState:      initialUpdateState,
	}
}

func (app *App) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/meta", app.handleMeta)
	mux.HandleFunc("/v1/update/check", app.handleCheckForUpdate)
	mux.HandleFunc("/v1/update/download", app.handleDownloadUpdate)
	mux.HandleFunc("/v1/update/restart", app.handleRestartUpdate)
	mux.HandleFunc("/v1/session/ready", app.handleSessionReady)
	mux.HandleFunc("/v1/session/failed", app.handleSessionFailed)
	mux.HandleFunc("/v1/session/restart-for-update", app.handleSessionRestartForUpdate)
	return mux
}

func (app *App) SessionStatus() SessionStatus {
	app.mu.RLock()
	defer app.mu.RUnlock()
	return app.sessionStatus
}

func (app *App) setSessionStatus(status SessionStatus) {
	app.mu.Lock()
	defer app.mu.Unlock()
	app.sessionStatus = status
}

func (app *App) ResetSessionStatus(status SessionStatus) {
	app.setSessionStatus(status)
}

func (app *App) UpdateState() CheckUpdateResponse {
	app.mu.RLock()
	defer app.mu.RUnlock()
	return cloneCheckUpdateResponse(app.updateState)
}

func (app *App) SetUpdateState(state CheckUpdateResponse) {
	app.mu.Lock()
	defer app.mu.Unlock()
	app.updateState = cloneCheckUpdateResponse(state)
}

func (app *App) handleMeta(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		writer.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	writeJSON(writer, http.StatusOK, MetaResponse{
		APIVersion:       ControlAPIVersion,
		BootstrapVersion: app.bootstrapVersion,
		SessionID:        app.sessionID,
	})
}

func (app *App) handleCheckForUpdate(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodPost {
		writer.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var body CheckUpdateRequest
	if err := decodeJSONBody(request, &body); err != nil {
		writeError(writer, http.StatusBadRequest, NewBootstrapError("bad-request", "invalid request body", nil, err))
		return
	}
	if current := app.UpdateState(); shouldServeCachedUpdateState(current) {
		writeJSON(writer, http.StatusOK, current)
		return
	}
	if app.checkForUpdate == nil {
		writeJSON(writer, http.StatusOK, CheckUpdateResponse{Status: UpdateStatusIdle})
		return
	}
	response, err := app.checkForUpdate(request.Context(), body)
	if err != nil {
		writeError(writer, statusCodeForError(err), err)
		return
	}
	app.SetUpdateState(response)
	writeJSON(writer, http.StatusOK, response)
}

func (app *App) handleDownloadUpdate(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodPost {
		writer.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var body DownloadUpdateRequest
	if err := decodeJSONBody(request, &body); err != nil {
		writeError(writer, http.StatusBadRequest, NewBootstrapError("bad-request", "invalid request body", nil, err))
		return
	}
	if app.downloadUpdate == nil {
		writeJSON(writer, http.StatusOK, DownloadUpdateResponse{Status: "accepted"})
		return
	}
	response, err := app.downloadUpdate(request.Context(), body)
	if err != nil {
		writeError(writer, statusCodeForError(err), err)
		return
	}
	writeJSON(writer, http.StatusOK, response)
}

func (app *App) handleRestartUpdate(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodPost {
		writer.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var body RestartUpdateRequest
	if err := decodeJSONBody(request, &body); err != nil {
		writeError(writer, http.StatusBadRequest, NewBootstrapError("bad-request", "invalid request body", nil, err))
		return
	}
	if app.restartUpdate == nil {
		writeJSON(writer, http.StatusOK, RestartUpdateResponse{Status: "accepted"})
		return
	}
	response, err := app.restartUpdate(request.Context(), body)
	if err != nil {
		writeError(writer, statusCodeForError(err), err)
		return
	}
	writeJSON(writer, http.StatusOK, response)
}

func (app *App) handleSessionReady(writer http.ResponseWriter, request *http.Request) {
	app.handleSessionEvent(writer, request, SessionStatusReady)
}

func (app *App) handleSessionFailed(writer http.ResponseWriter, request *http.Request) {
	app.handleSessionEvent(writer, request, SessionStatusFailed)
}

func (app *App) handleSessionRestartForUpdate(writer http.ResponseWriter, request *http.Request) {
	app.handleSessionEvent(writer, request, SessionStatusRestartRequested)
}

func (app *App) handleSessionEvent(writer http.ResponseWriter, request *http.Request, status SessionStatus) {
	if request.Method != http.MethodPost {
		writer.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var body SessionEventRequest
	if err := decodeJSONBody(request, &body); err != nil {
		writeError(writer, http.StatusBadRequest, NewBootstrapError("bad-request", "invalid request body", nil, err))
		return
	}
	app.setSessionStatus(status)
	if app.onSessionEvent != nil {
		app.onSessionEvent(status, body)
	}
	writeJSON(writer, http.StatusOK, SessionEventResponse{Status: status})
}

func decodeJSONBody(request *http.Request, target any) error {
	defer request.Body.Close()
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()
	return decoder.Decode(target)
}

func writeJSON(writer http.ResponseWriter, statusCode int, payload any) {
	writer.Header().Set("Content-Type", "application/json; charset=utf-8")
	writer.WriteHeader(statusCode)
	_ = json.NewEncoder(writer).Encode(payload)
}

func writeError(writer http.ResponseWriter, statusCode int, err error) {
	bootstrapErr, ok := err.(*BootstrapError)
	if !ok {
		bootstrapErr = NewBootstrapError("internal-error", err.Error(), nil, err)
	}
	writeJSON(writer, statusCode, ErrorResponse{
		Code:    bootstrapErr.Code,
		Message: bootstrapErr.Message,
		Details: bootstrapErr.Details,
	})
}

func statusCodeForError(err error) int {
	bootstrapErr, ok := err.(*BootstrapError)
	if !ok {
		return http.StatusInternalServerError
	}
	switch bootstrapErr.Code {
	case ErrCodeAPIVersionMismatch:
		return http.StatusConflict
	case ErrCodeLatestFetchFailed, ErrCodeManifestFetchFailed, ErrCodeManifestIntegrityFailed:
		return http.StatusBadGateway
	default:
		return http.StatusInternalServerError
	}
}

func shouldServeCachedUpdateState(state CheckUpdateResponse) bool {
	switch state.Status {
	case UpdateStatusDownloading, UpdateStatusReadyToRestart, UpdateStatusError:
		return true
	default:
		return false
	}
}

func cloneCheckUpdateResponse(state CheckUpdateResponse) CheckUpdateResponse {
	cloned := state
	if state.ChangedPackages != nil {
		cloned.ChangedPackages = append([]string(nil), state.ChangedPackages...)
	}
	if state.Progress != nil {
		progress := *state.Progress
		cloned.Progress = &progress
	}
	return cloned
}

type BuildShellLaunchSpecOptions struct {
	RootDir       string
	Current       CurrentState
	ControlOrigin string
	SessionID     string
	BaseEnv       []string
}

type ShellLaunchSpec struct {
	ExecutablePath   string
	WorkingDirectory string
	Environment      []string
}

func BuildShellLaunchSpec(options BuildShellLaunchSpecOptions) (ShellLaunchSpec, error) {
	rootDir := filepath.Clean(options.RootDir)
	shellRoot, err := ResolvePackageRoot(rootDir, options.Current, "shell")
	if err != nil {
		return ShellLaunchSpec{}, err
	}
	executablePath := filepath.Join(shellRoot, "NeoTTSApp.exe")
	if strings.TrimSpace(options.ControlOrigin) == "" {
		return ShellLaunchSpec{}, fmt.Errorf("bootstrap control origin is required")
	}
	return ShellLaunchSpec{
		ExecutablePath:   executablePath,
		WorkingDirectory: rootDir,
		Environment: mergeEnvironment(options.BaseEnv, map[string]string{
			"NEO_TTS_BOOTSTRAP_CONTROL_ORIGIN": options.ControlOrigin,
			"NEO_TTS_BOOTSTRAP_API_VERSION":    ControlAPIVersion,
			RuntimeDescriptorEnv:               filepath.Join(rootDir, "state", "current.json"),
			"NEO_TTS_OWNER_CONTROL_ORIGIN":     options.ControlOrigin,
			"NEO_TTS_OWNER_SESSION_ID":         options.SessionID,
		}),
	}, nil
}

func ResolvePackageRoot(rootDir string, current CurrentState, packageID string) (string, error) {
	packageState, ok := current.Packages[packageID]
	if !ok {
		return "", fmt.Errorf("package %q is missing from current runtime descriptor", packageID)
	}
	if root := strings.TrimSpace(packageState.Root); root != "" {
		return filepath.Clean(root), nil
	}
	if version := strings.TrimSpace(packageState.Version); version != "" {
		return filepath.Join(filepath.Clean(rootDir), "packages", packageID, version), nil
	}
	return "", fmt.Errorf("package %q does not have a resolved root", packageID)
}

func mergeEnvironment(baseEnv []string, overrides map[string]string) []string {
	envMap := make(map[string]string, len(baseEnv)+len(overrides))
	for _, entry := range baseEnv {
		parts := strings.SplitN(entry, "=", 2)
		if len(parts) != 2 {
			continue
		}
		envMap[parts[0]] = parts[1]
	}
	for key, value := range overrides {
		envMap[key] = value
	}
	merged := make([]string, 0, len(envMap))
	for key, value := range envMap {
		merged = append(merged, key+"="+value)
	}
	return merged
}

func ResolveBootstrapVersion(current CurrentState) string {
	if current.Packages != nil {
		if bootstrapState, ok := current.Packages["bootstrap"]; ok {
			if version := strings.TrimSpace(bootstrapState.Version); version != "" {
				return version
			}
		}
	}
	return "0.0.1"
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
