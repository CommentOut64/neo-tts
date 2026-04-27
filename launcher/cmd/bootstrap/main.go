package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
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
	if options.StartupSource != "update-agent" {
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
	}
	store := bootstrap.NewStateStore(options.RootDir)
	switcher := bootstrap.NewSwitcher(bootstrap.SwitcherOptions{
		RootDir: options.RootDir,
		Store:   store,
	})
	sessionID := buildBootstrapSessionID()
	currentState, err := store.LoadCurrent()
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	var pendingOfflineSource bootstrap.OfflineUpdateSource
	if options.StartupSource != "update-agent" {
		offlineResult, offlineErr := bootstrap.PrepareOfflineUpdateForStartup(context.Background(), bootstrap.OfflineStartupOptions{
			RootDir: options.RootDir,
			Current: currentState,
		})
		if offlineErr != nil {
			appendBootstrapLog(session.LogFilePath, "ERROR", "failed to prepare offline update source", map[string]any{"error": offlineErr.Error()})
		} else if offlineResult.Found {
			if err := bootstrap.StartOfflineUpdateNotice(options.RootDir, "正在验证离线更新包..."); err != nil {
				appendBootstrapLog(session.LogFilePath, "WARN", "failed to show offline update notice", map[string]any{"error": err.Error()})
			}
			candidate, stageErr := bootstrap.StageOfflineUpdateAndPrepareSwitch(context.Background(), bootstrap.OfflineSwitchOptions{
				SessionID: sessionID,
				Current:   currentState,
				Source:    offlineResult.Source,
				Manager:   updateManager,
				Switcher:  switcher,
				Progress: func(progress bootstrap.StageProgress) {
					_ = bootstrap.WriteOfflineUpdateNoticeStatus(options.RootDir, formatOfflineUpdateProgress(progress))
				},
			})
			if stageErr != nil {
				_ = bootstrap.WriteOfflineUpdateNoticeStatus(options.RootDir, "离线更新失败，将继续启动当前版本。")
				_ = bootstrap.FinishOfflineUpdateNotice(options.RootDir)
				appendBootstrapLog(session.LogFilePath, "ERROR", "failed to stage offline update", map[string]any{
					"releaseId": offlineResult.Source.ReleaseID,
					"error":     stageErr.Error(),
				})
			} else {
				previousState := currentState
				currentState = candidate
				pendingOfflineSource = offlineResult.Source
				appendBootstrapLog(session.LogFilePath, "INFO", "offline update staged and pending switch prepared", map[string]any{"releaseId": candidate.ReleaseID})
				if bootstrap.RequiresBootstrapSelfUpdate(previousState, candidate) {
					_ = bootstrap.WriteOfflineUpdateNoticeStatus(options.RootDir, "正在应用启动器更新...")
					if err := launchUpdateAgent(options.RootDir, previousState, candidate, session.LogFilePath); err != nil {
						_, _ = fmt.Fprintln(os.Stderr, err)
						os.Exit(1)
					}
					return
				}
			}
		}
	}
	pendingSwitch, err := store.LoadPendingSwitch()
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	awaitingCandidateValidation := options.StartupSource == "update-agent" && pendingSwitch.ReleaseID != "" || pendingOfflineSource.ReleaseID != ""

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
					targetPackages = bootstrap.CalculateChangedPackages(currentState, manifest, bootstrap.DefaultPackageOrder())
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

	for {
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

		result, err := runShellSession(runShellSessionOptions{
			LogFilePath:                 session.LogFilePath,
			SessionID:                   sessionID,
			LaunchSpec:                  launchSpec,
			App:                         app,
			AwaitingCandidateValidation: awaitingCandidateValidation,
			Switcher:                    switcher,
			CandidateState:              currentState,
			Store:                       store,
		})
		if err != nil {
			_, _ = fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}

		if result.CandidateRolledBack {
			_ = bootstrap.WriteOfflineUpdateNoticeStatus(options.RootDir, "离线更新失败，已回滚到当前版本。")
			_ = bootstrap.FinishOfflineUpdateNotice(options.RootDir)
			if pendingOfflineSource.ReleaseID != "" {
				_ = bootstrap.FailOfflineUpdateSource(pendingOfflineSource)
				pendingOfflineSource = bootstrap.OfflineUpdateSource{}
			}
			currentState, err = store.LoadCurrent()
			if err != nil {
				_, _ = fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			awaitingCandidateValidation = false
			app.ResetSessionStatus(bootstrap.SessionStatusBooting)
			continue
		}

		if result.SessionStatus == bootstrap.SessionStatusRestartRequested {
			pendingOfflineSource = bootstrap.OfflineUpdateSource{}
			releaseID := strings.TrimSpace(app.UpdateState().ReleaseID)
			stageSession, err := store.LoadStageSession(releaseID)
			if err != nil {
				_, _ = fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if stageSession.ReleaseID == "" {
				_, _ = fmt.Fprintln(os.Stderr, "staged update session is missing")
				os.Exit(1)
			}

			candidateState, err := switcher.PreparePendingSwitch(currentState, stageSession)
			if err != nil {
				_, _ = fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			if bootstrap.RequiresBootstrapSelfUpdate(currentState, candidateState) {
				if err := launchUpdateAgent(options.RootDir, currentState, candidateState, session.LogFilePath); err != nil {
					_, _ = fmt.Fprintln(os.Stderr, err)
					os.Exit(1)
				}
				return
			}

			currentState = candidateState
			awaitingCandidateValidation = true
			app.ResetSessionStatus(bootstrap.SessionStatusBooting)
			app.SetUpdateState(bootstrap.CheckUpdateResponse{Status: bootstrap.UpdateStatusIdle})
			continue
		}

		if awaitingCandidateValidation && result.SessionStatus == bootstrap.SessionStatusReady {
			if pendingOfflineSource.ReleaseID != "" {
				_ = bootstrap.FinishOfflineUpdateSource(pendingOfflineSource)
				pendingOfflineSource = bootstrap.OfflineUpdateSource{}
			}
			_ = bootstrap.FinishOfflineUpdateRelease(options.RootDir, currentState.ReleaseID)
			_ = bootstrap.FinishOfflineUpdateNotice(options.RootDir)
		}

		if result.ExitErr != nil {
			appendBootstrapLog(session.LogFilePath, "WARN", "product shell exited with error", map[string]any{
				"sessionId": sessionID,
				"error":     result.ExitErr.Error(),
			})
			if exitErr, ok := result.ExitErr.(*exec.ExitError); ok {
				os.Exit(exitErr.ExitCode())
			}
			_, _ = fmt.Fprintln(os.Stderr, result.ExitErr)
			os.Exit(1)
		}
		appendBootstrapLog(session.LogFilePath, "INFO", "product shell exited", map[string]any{
			"sessionId": sessionID,
			"status":    result.SessionStatus,
		})
		return
	}
}

func formatOfflineUpdateProgress(progress bootstrap.StageProgress) string {
	if progress.TotalPackages > 0 && progress.PackageID != "" {
		current := progress.CompletedPackages + 1
		if progress.Status == "package-complete" {
			current = progress.CompletedPackages
		}
		if current < 1 {
			current = 1
		}
		if current > progress.TotalPackages {
			current = progress.TotalPackages
		}
		return fmt.Sprintf("正在更新组件 %d/%d：%s", current, progress.TotalPackages, progress.PackageID)
	}
	return "正在准备离线更新..."
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

func appOrIdleState(state bootstrap.CheckUpdateResponse) bootstrap.CheckUpdateResponse {
	if state.Status == "" {
		return bootstrap.CheckUpdateResponse{Status: bootstrap.UpdateStatusUpToDate}
	}
	return state
}

type runShellSessionOptions struct {
	LogFilePath                 string
	SessionID                   string
	LaunchSpec                  bootstrap.ShellLaunchSpec
	App                         *bootstrap.App
	AwaitingCandidateValidation bool
	Switcher                    *bootstrap.Switcher
	CandidateState              bootstrap.CurrentState
	Store                       bootstrap.StateStore
}

type shellSessionResult struct {
	SessionStatus       bootstrap.SessionStatus
	ExitErr             error
	CandidateRolledBack bool
}

func runShellSession(options runShellSessionOptions) (shellSessionResult, error) {
	appendBootstrapLog(options.LogFilePath, "INFO", "launching product shell", map[string]any{
		"shellPath": options.LaunchSpec.ExecutablePath,
		"sessionId": options.SessionID,
	})
	child := exec.Command(options.LaunchSpec.ExecutablePath)
	child.Dir = options.LaunchSpec.WorkingDirectory
	child.Env = options.LaunchSpec.Environment
	if err := child.Start(); err != nil {
		appendBootstrapLog(options.LogFilePath, "ERROR", "failed to launch product shell", map[string]any{
			"shellPath": options.LaunchSpec.ExecutablePath,
			"sessionId": options.SessionID,
			"errorCode": bootstrap.ErrCodeStageFailed,
			"error":     err.Error(),
		})
		return shellSessionResult{}, err
	}
	appendBootstrapLog(options.LogFilePath, "INFO", "product shell started", map[string]any{
		"shellPath": options.LaunchSpec.ExecutablePath,
		"sessionId": options.SessionID,
		"pid":       child.Process.Pid,
	})

	waitCh := make(chan error, 1)
	go func() {
		waitCh <- child.Wait()
	}()

	if options.AwaitingCandidateValidation {
		deadline := time.NewTimer(30 * time.Second)
		ticker := time.NewTicker(200 * time.Millisecond)
		defer deadline.Stop()
		defer ticker.Stop()

		for {
			select {
			case err := <-waitCh:
				if rollbackErr := options.Switcher.RollbackPendingSwitch(bootstrap.ErrCodeCandidateExit, "candidate process exited before reporting ready"); rollbackErr != nil {
					return shellSessionResult{}, rollbackErr
				}
				appendBootstrapLog(options.LogFilePath, "WARN", "candidate shell exited before ready and rollback was applied", map[string]any{
					"sessionId":  options.SessionID,
					"errorCode":  bootstrap.ErrCodeCandidateExit,
					"releaseId":  options.CandidateState.ReleaseID,
					"exitReason": errorString(err),
				})
				return shellSessionResult{
					SessionStatus:       options.App.SessionStatus(),
					ExitErr:             err,
					CandidateRolledBack: true,
				}, nil
			case <-deadline.C:
				_ = child.Process.Kill()
				err := <-waitCh
				if rollbackErr := options.Switcher.RollbackPendingSwitch(bootstrap.ErrCodeCandidateReadyTimeout, "candidate did not report ready before timeout"); rollbackErr != nil {
					return shellSessionResult{}, rollbackErr
				}
				appendBootstrapLog(options.LogFilePath, "WARN", "candidate shell timed out before ready and rollback was applied", map[string]any{
					"sessionId":  options.SessionID,
					"errorCode":  bootstrap.ErrCodeCandidateReadyTimeout,
					"releaseId":  options.CandidateState.ReleaseID,
					"exitReason": errorString(err),
				})
				return shellSessionResult{
					SessionStatus:       options.App.SessionStatus(),
					ExitErr:             err,
					CandidateRolledBack: true,
				}, nil
			case <-ticker.C:
				switch options.App.SessionStatus() {
				case bootstrap.SessionStatusReady:
					if err := options.Switcher.CommitPendingSwitch(options.CandidateState); err != nil {
						return shellSessionResult{}, err
					}
					appendBootstrapLog(options.LogFilePath, "INFO", "candidate shell reported ready and switch was committed", map[string]any{
						"sessionId": options.SessionID,
						"releaseId": options.CandidateState.ReleaseID,
					})
					err := <-waitCh
					return shellSessionResult{
						SessionStatus: options.App.SessionStatus(),
						ExitErr:       err,
					}, nil
				case bootstrap.SessionStatusFailed:
					_ = child.Process.Kill()
					err := <-waitCh
					if rollbackErr := options.Switcher.RollbackPendingSwitch(bootstrap.ErrCodeCandidateExit, "candidate reported startup failure"); rollbackErr != nil {
						return shellSessionResult{}, rollbackErr
					}
					appendBootstrapLog(options.LogFilePath, "WARN", "candidate shell reported startup failure and rollback was applied", map[string]any{
						"sessionId":  options.SessionID,
						"releaseId":  options.CandidateState.ReleaseID,
						"errorCode":  bootstrap.ErrCodeCandidateExit,
						"exitReason": errorString(err),
					})
					return shellSessionResult{
						SessionStatus:       options.App.SessionStatus(),
						ExitErr:             err,
						CandidateRolledBack: true,
					}, nil
				}
			}
		}
	}

	err := <-waitCh
	return shellSessionResult{
		SessionStatus: options.App.SessionStatus(),
		ExitErr:       err,
	}, nil
}

func launchUpdateAgent(rootDir string, current bootstrap.CurrentState, candidate bootstrap.CurrentState, logFilePath string) error {
	plan, err := bootstrap.BuildSelfUpdatePlan(rootDir, candidate)
	if err != nil {
		return err
	}
	planPath, err := bootstrap.SaveSelfUpdatePlan(rootDir, plan)
	if err != nil {
		return err
	}

	updateAgentPath := filepath.Join(rootDir, "NeoTTSUpdateAgent.exe")
	command := exec.Command(updateAgentPath, "--plan", planPath, "--bootstrap-pid", fmt.Sprintf("%d", os.Getpid()))
	command.Dir = rootDir
	if err := command.Start(); err != nil {
		return err
	}
	appendBootstrapLog(logFilePath, "INFO", "spawned update-agent for bootstrap self-update", map[string]any{
		"planPath":         planPath,
		"updateAgentPath":  updateAgentPath,
		"candidateRelease": candidate.ReleaseID,
		"currentRelease":   current.ReleaseID,
		"pid":              command.Process.Pid,
	})
	return command.Process.Release()
}

func errorString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
