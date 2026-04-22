package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"

	"neo-tts/launcher/internal/bootstrap"
	"neo-tts/launcher/internal/logging"
	winplatform "neo-tts/launcher/internal/platform/windows"
)

type releaseMetadataCache struct {
	latest   bootstrap.ChannelLatest
	manifest bootstrap.ReleaseManifest
}

func main() {
	workingDirectory, err := os.Getwd()
	if err != nil {
		workingDirectory = "."
	}

	executablePath, err := os.Executable()
	if err != nil {
		executablePath = os.Args[0]
	}

	options, err := bootstrap.ParseOptions(os.Args[1:], executablePath, workingDirectory)
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	isElevated, _ := winplatform.IsCurrentProcessElevated()
	session, _ := logging.Bootstrap(options.RootDir, logging.StartupContext{
		WorkingDirectory: options.RootDir,
		ExecutablePath:   executablePath,
		Arguments:        os.Args[1:],
		IsElevated:       isElevated,
		StartupSource:    options.StartupSource,
	})
	if session.LogFilePath != "" {
		appendBootstrapLog(session.LogFilePath, "INFO", "bootstrap initialized", map[string]any{
			"channel":       options.Channel,
			"startupSource": options.StartupSource,
		})
	}

	updateManager := bootstrap.NewUpdateManager(bootstrap.UpdateManagerOptions{
		RootDir: options.RootDir,
		Log: func(level string, message string, fields map[string]any) {
			appendBootstrapLog(session.LogFilePath, level, message, fields)
		},
	})
	if recovered, err := updateManager.RecoverPendingSwitch(); err != nil {
		if session.LogFilePath != "" {
			appendBootstrapLog(session.LogFilePath, "ERROR", "failed to recover interrupted pending switch", map[string]any{
				"errorCode":    bootstrap.ErrCodeSwitchFailed,
				"releasePhase": "pending-switch-recovery",
				"error":        err.Error(),
			})
		}
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	} else if recovered && session.LogFilePath != "" {
		appendBootstrapLog(session.LogFilePath, "WARN", "recovered interrupted pending switch", map[string]any{
			"errorCode": bootstrap.ErrCodeSwitchFailed,
		})
	}
	store := bootstrap.NewStateStore(options.RootDir)
	currentState, err := store.LoadCurrent()
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	initialUpdateState := bootstrap.CheckUpdateResponse{Status: bootstrap.UpdateStatusIdle}
	if resumable, ok, err := updateManager.FindResumableStageSession(); err != nil {
		if session.LogFilePath != "" {
			appendBootstrapLog(session.LogFilePath, "ERROR", "failed to inspect staged update sessions", map[string]any{
				"error": err.Error(),
			})
		}
	} else if ok {
		initialUpdateState = bootstrap.CheckUpdateResponse{
			Status:                 bootstrap.UpdateStatusReadyToRestart,
			ReleaseID:              resumable.ReleaseID,
			NotesURL:               resumable.NotesURL,
			ChangedPackages:        append([]string(nil), resumable.TargetPackages...),
			EstimatedDownloadBytes: resumable.EstimatedDownloadBytes,
			Progress: &bootstrap.UpdateProgress{
				TotalPackages:     len(resumable.TargetPackages),
				CompletedPackages: len(resumable.CompletedPackages),
			},
		}
		if session.LogFilePath != "" {
			appendBootstrapLog(session.LogFilePath, "INFO", "found resumable staged update session", map[string]any{
				"releaseId": resumable.ReleaseID,
				"status":    resumable.Status,
			})
		}
	}
	if err := updateManager.CleanupObsoletePackages(); err != nil && session.LogFilePath != "" {
		appendBootstrapLog(session.LogFilePath, "WARN", "cleanup finished with non-fatal errors", map[string]any{
			"error": err.Error(),
		})
	}

	latestURL := resolveLatestURL(options.Channel)
	sessionID := buildBootstrapSessionID()
	var snapshotMu sync.Mutex
	var cached releaseMetadataCache

	var app *bootstrap.App
	app = bootstrap.NewApp(bootstrap.AppOptions{
		BootstrapVersion:   bootstrap.ResolveBootstrapVersion(currentState),
		SessionID:          sessionID,
		InitialUpdateState: initialUpdateState,
		CheckForUpdate: func(ctx context.Context, _ bootstrap.CheckUpdateRequest) (bootstrap.CheckUpdateResponse, error) {
			if strings.TrimSpace(latestURL) == "" {
				state := app.UpdateState()
				if state.Status != "" && state.Status != bootstrap.UpdateStatusIdle {
					return state, nil
				}
				return bootstrap.CheckUpdateResponse{Status: bootstrap.UpdateStatusUpToDate}, nil
			}
			current, err := store.LoadCurrent()
			if err != nil {
				return bootstrap.CheckUpdateResponse{}, err
			}
			latest, manifest, err := bootstrap.FetchLatestRelease(ctx, nil, latestURL)
			if err != nil {
				return bootstrap.CheckUpdateResponse{}, err
			}
			snapshotMu.Lock()
			cached = releaseMetadataCache{latest: latest, manifest: manifest}
			snapshotMu.Unlock()
			response, err := bootstrap.CheckForUpdate(ctx, bootstrap.UpdateCheckOptions{
				LatestURL:        latestURL,
				CurrentState:     current,
				BootstrapVersion: bootstrap.ResolveBootstrapVersion(current),
			})
			if err != nil {
				return bootstrap.CheckUpdateResponse{}, err
			}
			failedRelease, failedErr := store.LoadFailedRelease()
			if failedErr == nil && failedRelease.ReleaseID != "" && failedRelease.ReleaseID == response.ReleaseID {
				return rollbackPromptState(failedRelease), nil
			}
			return response, nil
		},
		DownloadUpdate: func(_ context.Context, request bootstrap.DownloadUpdateRequest) (bootstrap.DownloadUpdateResponse, error) {
			current := app.UpdateState()
			releaseID := strings.TrimSpace(request.ReleaseID)
			if releaseID == "" {
				releaseID = current.ReleaseID
			}
			if releaseID == "" {
				return bootstrap.DownloadUpdateResponse{}, bootstrap.NewBootstrapError(
					bootstrap.ErrCodeStageFailed,
					"release id is required",
					nil,
					nil,
				)
			}
			if current.Status == bootstrap.UpdateStatusReadyToRestart && current.ReleaseID == releaseID {
				return bootstrap.DownloadUpdateResponse{
					Status:    string(bootstrap.UpdateStatusReadyToRestart),
					ReleaseID: current.ReleaseID,
					Progress:  current.Progress,
					Message:   "update already staged",
				}, nil
			}
			if strings.TrimSpace(latestURL) == "" {
				return bootstrap.DownloadUpdateResponse{}, bootstrap.NewBootstrapError(
					bootstrap.ErrCodeLatestFetchFailed,
					"latest release metadata url is not configured",
					nil,
					nil,
				)
			}

			app.SetUpdateState(bootstrap.CheckUpdateResponse{
				Status:                 bootstrap.UpdateStatusDownloading,
				ReleaseID:              releaseID,
				NotesURL:               current.NotesURL,
				ChangedPackages:        append([]string(nil), current.ChangedPackages...),
				EstimatedDownloadBytes: current.EstimatedDownloadBytes,
				Progress: &bootstrap.UpdateProgress{
					TotalPackages:     len(current.ChangedPackages),
					CompletedPackages: 0,
				},
			})
			go func() {
				downloadCtx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
				defer cancel()

				latest, manifest, err := cachedReleaseMetadata(downloadCtx, latestURL, &snapshotMu, &cached)
				if err != nil {
					state := bootstrap.CheckUpdateResponse{
						Status:       bootstrap.UpdateStatusError,
						ReleaseID:    releaseID,
						ErrorCode:    bootstrap.ErrCodeManifestFetchFailed,
						ErrorMessage: err.Error(),
					}
					app.SetUpdateState(state)
					appendBootstrapLog(session.LogFilePath, "ERROR", "failed to load release metadata before staging", map[string]any{
						"releaseId": releaseID,
						"sessionId": sessionID,
						"errorCode": bootstrap.ErrCodeManifestFetchFailed,
						"error":     err.Error(),
					})
					return
				}
				targetPackages := append([]string(nil), current.ChangedPackages...)
				if len(targetPackages) == 0 {
					targetPackages = calculateChangedPackages(currentState, manifest)
				}
				stageSession, stageErr := updateManager.StageRelease(downloadCtx, bootstrap.StageReleaseRequest{
					SessionID:              sessionID,
					ReleaseID:              releaseID,
					ManifestSHA256:         latest.ManifestSHA256,
					NotesURL:               manifest.NotesURL,
					EstimatedDownloadBytes: current.EstimatedDownloadBytes,
					TargetPackages:         targetPackages,
					RemotePackages:         manifest.Packages,
					Progress: func(progress bootstrap.StageProgress) {
						state := app.UpdateState()
						state.Status = bootstrap.UpdateStatusDownloading
						state.ReleaseID = releaseID
						state.NotesURL = manifest.NotesURL
						state.ChangedPackages = append([]string(nil), targetPackages...)
						state.Progress = &bootstrap.UpdateProgress{
							TotalPackages:         progress.TotalPackages,
							CompletedPackages:     progress.CompletedPackages,
							CurrentPackageID:      progress.PackageID,
							CurrentPackageVersion: progress.PackageVersion,
							CurrentPackageBytes:   progress.CurrentBytes,
							CurrentPackageTotal:   progress.TotalBytes,
						}
						app.SetUpdateState(state)
					},
				})
				if stageErr != nil {
					bootstrapErr, ok := stageErr.(*bootstrap.BootstrapError)
					errorCode := bootstrap.ErrCodeStageFailed
					if ok {
						errorCode = bootstrapErr.Code
					}
					app.SetUpdateState(bootstrap.CheckUpdateResponse{
						Status:          bootstrap.UpdateStatusError,
						ReleaseID:       releaseID,
						NotesURL:        manifest.NotesURL,
						ChangedPackages: append([]string(nil), targetPackages...),
						ErrorCode:       errorCode,
						ErrorMessage:    stageErr.Error(),
					})
					appendBootstrapLog(session.LogFilePath, "ERROR", "release staging failed", map[string]any{
						"releaseId": releaseID,
						"sessionId": sessionID,
						"errorCode": errorCode,
						"error":     stageErr.Error(),
					})
					return
				}
				app.SetUpdateState(bootstrap.CheckUpdateResponse{
					Status:                 bootstrap.UpdateStatusReadyToRestart,
					ReleaseID:              releaseID,
					NotesURL:               manifest.NotesURL,
					ChangedPackages:        append([]string(nil), stageSession.TargetPackages...),
					EstimatedDownloadBytes: stageSession.EstimatedDownloadBytes,
					Progress: &bootstrap.UpdateProgress{
						TotalPackages:     len(stageSession.TargetPackages),
						CompletedPackages: len(stageSession.CompletedPackages),
					},
				})
			}()
			downloadState := app.UpdateState()
			return bootstrap.DownloadUpdateResponse{
				Status:    string(bootstrap.UpdateStatusDownloading),
				ReleaseID: releaseID,
				Progress:  downloadState.Progress,
				Message:   "staging started",
			}, nil
		},
		RestartUpdate: func(_ context.Context, request bootstrap.RestartUpdateRequest) (bootstrap.RestartUpdateResponse, error) {
			state := app.UpdateState()
			releaseID := strings.TrimSpace(request.ReleaseID)
			if releaseID == "" {
				releaseID = state.ReleaseID
			}
			return bootstrap.RestartUpdateResponse{
				Status:    "switching",
				ReleaseID: releaseID,
			}, nil
		},
		OnSessionEvent: func(status bootstrap.SessionStatus, request bootstrap.SessionEventRequest) {
			appendBootstrapLog(session.LogFilePath, "INFO", "received session lifecycle event", map[string]any{
				"sessionId": request.SessionID,
				"status":    status,
				"code":      request.Code,
				"message":   request.Message,
			})
		},
	})
	controlServer, err := bootstrap.StartControlServer(app)
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer func() {
		_ = controlServer.Close(context.Background())
	}()
	appendBootstrapLog(session.LogFilePath, "INFO", "bootstrap control server started", map[string]any{
		"origin":    controlServer.Origin,
		"sessionId": sessionID,
	})

	launchSpec, err := bootstrap.BuildShellLaunchSpec(bootstrap.BuildShellLaunchSpecOptions{
		RootDir:       options.RootDir,
		Current:       currentState,
		ControlOrigin: controlServer.Origin,
		SessionID:     sessionID,
		BaseEnv:       os.Environ(),
	})
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	appendBootstrapLog(session.LogFilePath, "INFO", "launching product shell", map[string]any{
		"shellPath": launchSpec.ExecutablePath,
		"sessionId": sessionID,
	})
	child := exec.Command(launchSpec.ExecutablePath)
	child.Dir = launchSpec.WorkingDirectory
	child.Env = launchSpec.Environment
	if err := child.Start(); err != nil {
		appendBootstrapLog(session.LogFilePath, "ERROR", "failed to launch product shell", map[string]any{
			"shellPath": launchSpec.ExecutablePath,
			"sessionId": sessionID,
			"errorCode": bootstrap.ErrCodeStageFailed,
			"error":     err.Error(),
		})
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	appendBootstrapLog(session.LogFilePath, "INFO", "product shell started", map[string]any{
		"shellPath": launchSpec.ExecutablePath,
		"sessionId": sessionID,
		"pid":       child.Process.Pid,
	})
	if err := child.Wait(); err != nil {
		appendBootstrapLog(session.LogFilePath, "WARN", "product shell exited with error", map[string]any{
			"sessionId": sessionID,
			"error":     err.Error(),
		})
		if exitErr, ok := err.(*exec.ExitError); ok {
			os.Exit(exitErr.ExitCode())
		}
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	appendBootstrapLog(session.LogFilePath, "INFO", "product shell exited", map[string]any{
		"sessionId": sessionID,
		"status":    app.SessionStatus(),
	})
}

func appendBootstrapLog(logFilePath string, level string, message string, fields map[string]any) {
	if logFilePath == "" {
		return
	}
	_ = logging.Append(logFilePath, bootstrap.FormatLogEntry(level, "bootstrap", message, fields))
}

func buildBootstrapSessionID() string {
	return fmt.Sprintf("bootstrap-%d-%d", os.Getpid(), time.Now().UTC().UnixNano())
}

func resolveLatestURL(channel string) string {
	if exact := strings.TrimSpace(os.Getenv("NEO_TTS_UPDATE_LATEST_URL")); exact != "" {
		return exact
	}
	base := strings.TrimSpace(os.Getenv("NEO_TTS_UPDATE_BASE_URL"))
	if base == "" {
		return ""
	}
	return strings.TrimRight(base, "/") + "/channels/" + channel + "/latest.json"
}

func cachedReleaseMetadata(
	ctx context.Context,
	latestURL string,
	mu *sync.Mutex,
	cached *releaseMetadataCache,
) (bootstrap.ChannelLatest, bootstrap.ReleaseManifest, error) {
	mu.Lock()
	snapshot := *cached
	mu.Unlock()
	if snapshot.latest.ReleaseID != "" && snapshot.manifest.ReleaseID != "" {
		return snapshot.latest, snapshot.manifest, nil
	}
	latest, manifest, err := bootstrap.FetchLatestRelease(ctx, nil, latestURL)
	if err != nil {
		return bootstrap.ChannelLatest{}, bootstrap.ReleaseManifest{}, err
	}
	mu.Lock()
	cached.latest = latest
	cached.manifest = manifest
	mu.Unlock()
	return latest, manifest, nil
}

func rollbackPromptState(failed bootstrap.FailedReleaseState) bootstrap.CheckUpdateResponse {
	return bootstrap.CheckUpdateResponse{
		Status:       bootstrap.UpdateStatusError,
		ReleaseID:    failed.ReleaseID,
		ErrorCode:    failed.Code,
		ErrorMessage: "检测到上次切换失败，已回滚到当前稳定版本，可稍后重试。",
	}
}

func calculateChangedPackages(current bootstrap.CurrentState, manifest bootstrap.ReleaseManifest) []string {
	order := bootstrap.DefaultPackageOrder()
	changed := make([]string, 0, len(order))
	for _, packageID := range order {
		remotePackage, ok := manifest.Packages[packageID]
		if !ok {
			continue
		}
		currentPackage, ok := current.Packages[packageID]
		if ok && currentPackage.Version == remotePackage.Version {
			continue
		}
		changed = append(changed, packageID)
	}
	return changed
}

func appOrIdleState(state bootstrap.CheckUpdateResponse) bootstrap.CheckUpdateResponse {
	if state.Status == "" {
		return bootstrap.CheckUpdateResponse{Status: bootstrap.UpdateStatusUpToDate}
	}
	return state
}
