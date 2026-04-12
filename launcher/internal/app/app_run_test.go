package app_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"reflect"
	"testing"
	"time"

	app "neo-tts/launcher/internal/app"
	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/control"
	"neo-tts/launcher/internal/state"
	"neo-tts/launcher/internal/supervisor"
)

type stubLock struct{}

func (stubLock) Close() error { return nil }

func TestAppRunsBootSequenceInExpectedOrder(t *testing.T) {
	order := make([]string, 0, 10)

	result, err := app.Run(context.Background(), app.RunOptions{
		ProjectRoot:   `F:\neo-tts`,
		StartupSource: "double-click",
	}, app.AppDeps{
		LoadConfig: func(projectRoot string, overrides config.CLIOverrides) (config.Config, error) {
			order = append(order, "config")
			return config.Config{
				ProjectRoot:  projectRoot,
				RuntimeMode:  "dev",
				FrontendMode: "web",
				Backend: config.BackendConfig{
					Mode: "owned",
					Host: "127.0.0.1",
					Port: 18600,
				},
			}, nil
		},
		BuildStartupContext: func(projectRoot string, startupSource string) (app.StartupContext, error) {
			order = append(order, "startup")
			return app.StartupContext{
				ProjectRoot:   projectRoot,
				StartupSource: startupSource,
				IsElevated:    true,
				InstanceName:  "instance-name",
			}, nil
		},
		AcquireInstanceLock: func(name string) (app.InstanceLock, bool, error) {
			order = append(order, "lock")
			return stubLock{}, true, nil
		},
		LoadState: func(projectRoot string) (state.RuntimeState, error) {
			order = append(order, "load-state")
			return state.RuntimeState{}, nil
		},
		SaveState: func(projectRoot string, runtimeState state.RuntimeState) (string, error) {
			order = append(order, "save:"+runtimeState.LastPhase)
			return "", nil
		},
		StartOwnedProcessGroup: func(ctx context.Context, cfg config.Config) (app.OwnedProcessGroup, error) {
			order = append(order, "process-group")
			return stubOwnedProcessGroup{}, nil
		},
		StartOwnerControl: func(ctx context.Context, cfg config.Config, shutdown context.CancelFunc) (app.OwnerControlHandle, error) {
			order = append(order, "control")
			return stubOwnerControlHandle{session: control.Session{
				ID:            "session-1",
				ControlOrigin: "http://127.0.0.1:43125",
				ControlToken:  "owner-token",
			}}, nil
		},
		EnsureBackend: func(ctx context.Context, cfg config.Config, previous state.RuntimeState, ownerSession *control.Session) (supervisor.BackendResult, error) {
			order = append(order, "backend")
			if ownerSession == nil || ownerSession.ControlToken != "owner-token" {
				t.Fatalf("EnsureBackend ownerSession = %+v, want injected session", ownerSession)
			}
			return supervisor.BackendResult{
				State: state.RuntimeState{
					Backend: state.BackendState{
						Mode:   "owned",
						PID:    24680,
						Port:   18600,
						Origin: "http://127.0.0.1:18600",
					},
					LastPhase: app.PhaseBackendReady,
				},
			}, nil
		},
		StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error) {
			order = append(order, "frontend")
			return supervisor.FrontendResult{
				State: state.RuntimeState{
					FrontendHost: state.FrontendHostState{
						Kind:          "vite",
						PID:           97531,
						Port:          5175,
						Origin:        "http://localhost:5175",
						Command:       "npm run dev",
						BrowserOpened: true,
					},
					LastPhase: app.PhaseRunning,
				},
			}, nil
		},
		WaitForSupervisor: func(ctx context.Context, cfg config.Config, current state.RuntimeState, backendResult supervisor.BackendResult, frontendResult supervisor.FrontendResult) error {
			order = append(order, "wait")
			return nil
		},
	})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	wantOrder := []string{
		"config",
		"startup",
		"lock",
		"load-state",
		"save:booting",
		"control",
		"process-group",
		"backend",
		"save:backend-ready",
		"frontend",
		"save:running",
		"wait",
	}
	if !reflect.DeepEqual(order, wantOrder) {
		t.Fatalf("order = %#v, want %#v", order, wantOrder)
	}
	if result.SilentExit {
		t.Fatal("SilentExit = true, want false")
	}
	if result.State.StartupSource != "double-click" {
		t.Fatalf("StartupSource = %q, want double-click", result.State.StartupSource)
	}
	if !result.State.IsElevated {
		t.Fatal("IsElevated = false, want true")
	}
}

func TestSecondLaunchExitsSilentlyWhenHealthyWebInstanceExists(t *testing.T) {
	order := make([]string, 0, 6)

	result, err := app.Run(context.Background(), app.RunOptions{
		ProjectRoot:   `F:\neo-tts`,
		StartupSource: "double-click",
	}, app.AppDeps{
		LoadConfig: func(projectRoot string, overrides config.CLIOverrides) (config.Config, error) {
			order = append(order, "config")
			return config.Config{
				ProjectRoot:  projectRoot,
				RuntimeMode:  "dev",
				FrontendMode: "web",
				Backend: config.BackendConfig{
					Mode: "owned",
					Host: "127.0.0.1",
					Port: 18600,
				},
			}, nil
		},
		BuildStartupContext: func(projectRoot string, startupSource string) (app.StartupContext, error) {
			order = append(order, "startup")
			return app.StartupContext{
				ProjectRoot:   projectRoot,
				StartupSource: startupSource,
				InstanceName:  "instance-name",
			}, nil
		},
		AcquireInstanceLock: func(name string) (app.InstanceLock, bool, error) {
			order = append(order, "lock")
			return stubLock{}, false, nil
		},
		LoadState: func(projectRoot string) (state.RuntimeState, error) {
			order = append(order, "load-state")
			return state.RuntimeState{
				FrontendHost: state.FrontendHostState{
					Origin: "http://localhost:5175",
				},
			}, nil
		},
		IsExistingWebInstanceHealthy: func(ctx context.Context, existing state.RuntimeState) bool {
			order = append(order, "existing-healthy")
			return true
		},
		EnsureBackend: func(ctx context.Context, cfg config.Config, previous state.RuntimeState, ownerSession *control.Session) (supervisor.BackendResult, error) {
			return supervisor.BackendResult{}, errors.New("EnsureBackend should not be called")
		},
		StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error) {
			return supervisor.FrontendResult{}, errors.New("StartFrontend should not be called")
		},
		WaitForSupervisor: func(ctx context.Context, cfg config.Config, current state.RuntimeState, backendResult supervisor.BackendResult, frontendResult supervisor.FrontendResult) error {
			return errors.New("WaitForSupervisor should not be called")
		},
	})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	wantOrder := []string{"config", "startup", "lock", "load-state", "existing-healthy"}
	if !reflect.DeepEqual(order, wantOrder) {
		t.Fatalf("order = %#v, want %#v", order, wantOrder)
	}
	if !result.SilentExit {
		t.Fatal("SilentExit = false, want true")
	}
}

func TestAppRejectsProductElectronProfileBeforeStartingRuntime(t *testing.T) {
	startedRuntime := false
	_, err := app.Run(context.Background(), app.RunOptions{
		ProjectRoot:   `F:\neo-tts`,
		StartupSource: "double-click",
	}, app.AppDeps{
		LoadConfig: func(projectRoot string, overrides config.CLIOverrides) (config.Config, error) {
			return config.Config{
				ProjectRoot:  projectRoot,
				RuntimeMode:  "product",
				FrontendMode: "electron",
				Backend: config.BackendConfig{
					Mode: "owned",
					Host: "127.0.0.1",
					Port: 18600,
				},
			}, nil
		},
		BuildStartupContext: func(projectRoot string, startupSource string) (app.StartupContext, error) {
			return app.StartupContext{
				ProjectRoot:   projectRoot,
				StartupSource: startupSource,
				InstanceName:  "instance-name",
			}, nil
		},
		AcquireInstanceLock: func(name string) (app.InstanceLock, bool, error) {
			return stubLock{}, true, nil
		},
		LoadState: func(projectRoot string) (state.RuntimeState, error) {
			return state.RuntimeState{}, nil
		},
		SaveState: func(projectRoot string, runtimeState state.RuntimeState) (string, error) {
			return "", nil
		},
		EnsureBackend: func(ctx context.Context, cfg config.Config, previous state.RuntimeState, ownerSession *control.Session) (supervisor.BackendResult, error) {
			startedRuntime = true
			return supervisor.BackendResult{}, nil
		},
		StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error) {
			startedRuntime = true
			return supervisor.FrontendResult{}, nil
		},
		WaitForSupervisor: func(ctx context.Context, cfg config.Config, current state.RuntimeState, backendResult supervisor.BackendResult, frontendResult supervisor.FrontendResult) error {
			startedRuntime = true
			return nil
		},
	})
	if !errors.Is(err, app.ErrUnsupportedLauncherProfile) {
		t.Fatalf("Run error = %v, want ErrUnsupportedLauncherProfile", err)
	}
	if startedRuntime {
		t.Fatal("legacy runtime startup hooks were called for unsupported launcher profile")
	}
}

func TestFreshLaunchDoesNotInheritStaleBrowserOpenedFlag(t *testing.T) {
	previousState := state.RuntimeState{
		LauncherPID: 99999,
		Backend: state.BackendState{
			Mode:    "owned",
			PID:     24680,
			Port:    18600,
			Origin:  "http://127.0.0.1:18600",
			Command: "python -m backend.app.cli --port 18600",
		},
		FrontendHost: state.FrontendHostState{
			Kind:          "vite",
			PID:           97531,
			Port:          5175,
			Origin:        "http://localhost:5175",
			Command:       "npm run dev",
			BrowserOpened: true,
		},
		LastPhase: "running",
	}

	bootingSeen := false
	ensureBackendSawPrevious := false

	_, err := app.Run(context.Background(), app.RunOptions{
		ProjectRoot:   `F:\neo-tts`,
		StartupSource: "double-click",
	}, app.AppDeps{
		LoadConfig: func(projectRoot string, overrides config.CLIOverrides) (config.Config, error) {
			return config.Config{
				ProjectRoot:  projectRoot,
				RuntimeMode:  "dev",
				FrontendMode: "web",
				Backend: config.BackendConfig{
					Mode: "owned",
					Host: "127.0.0.1",
					Port: 18600,
				},
			}, nil
		},
		BuildStartupContext: func(projectRoot string, startupSource string) (app.StartupContext, error) {
			return app.StartupContext{
				ProjectRoot:   projectRoot,
				StartupSource: startupSource,
				InstanceName:  "instance-name",
			}, nil
		},
		AcquireInstanceLock: func(name string) (app.InstanceLock, bool, error) {
			return stubLock{}, true, nil
		},
		LoadState: func(projectRoot string) (state.RuntimeState, error) {
			return previousState, nil
		},
		SaveState: func(projectRoot string, runtimeState state.RuntimeState) (string, error) {
			if runtimeState.LastPhase == "booting" {
				bootingSeen = true
				if runtimeState.FrontendHost.BrowserOpened {
					t.Fatal("booting state inherited stale BrowserOpened=true")
				}
			}
			return "", nil
		},
		StartOwnedProcessGroup: func(ctx context.Context, cfg config.Config) (app.OwnedProcessGroup, error) {
			return stubOwnedProcessGroup{}, nil
		},
		StartOwnerControl: func(ctx context.Context, cfg config.Config, shutdown context.CancelFunc) (app.OwnerControlHandle, error) {
			return stubOwnerControlHandle{session: control.Session{
				ID:            "session-1",
				ControlOrigin: "http://127.0.0.1:43125",
				ControlToken:  "owner-token",
			}}, nil
		},
		EnsureBackend: func(ctx context.Context, cfg config.Config, previous state.RuntimeState, ownerSession *control.Session) (supervisor.BackendResult, error) {
			ensureBackendSawPrevious = previous.FrontendHost.BrowserOpened &&
				previous.FrontendHost.PID == 97531 &&
				previous.Backend.PID == 24680
			if ownerSession == nil || ownerSession.ID != "session-1" {
				t.Fatalf("EnsureBackend ownerSession = %+v, want session-1", ownerSession)
			}
			return supervisor.BackendResult{
				State: state.RuntimeState{
					Backend: state.BackendState{
						Mode:   "owned",
						PID:    13579,
						Port:   18600,
						Origin: "http://127.0.0.1:18600",
					},
					LastPhase: app.PhaseBackendReady,
				},
			}, nil
		},
		StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error) {
			if current.FrontendHost.BrowserOpened {
				t.Fatal("fresh launch should not inherit stale BrowserOpened=true")
			}
			return supervisor.FrontendResult{
				State: state.RuntimeState{
					FrontendHost: state.FrontendHostState{
						Kind:          "vite",
						PID:           86420,
						Port:          5175,
						Origin:        "http://localhost:5175",
						Command:       "npm run dev",
						BrowserOpened: true,
					},
					LastPhase: app.PhaseRunning,
				},
			}, nil
		},
		WaitForSupervisor: func(ctx context.Context, cfg config.Config, current state.RuntimeState, backendResult supervisor.BackendResult, frontendResult supervisor.FrontendResult) error {
			return nil
		},
	})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	if !bootingSeen {
		t.Fatal("booting state was not saved")
	}
	if !ensureBackendSawPrevious {
		t.Fatal("EnsureBackend did not receive stale previous state for cleanup")
	}
}

func TestAppControlShutdownCancelsSupervisorContext(t *testing.T) {
	var ownerSession *control.Session

	_, err := app.Run(context.Background(), app.RunOptions{
		ProjectRoot:   `F:\neo-tts`,
		StartupSource: "double-click",
	}, app.AppDeps{
		LoadConfig: func(projectRoot string, overrides config.CLIOverrides) (config.Config, error) {
			return config.Config{
				ProjectRoot:  projectRoot,
				RuntimeMode:  "dev",
				FrontendMode: "web",
				Backend: config.BackendConfig{
					Mode: "owned",
					Host: "127.0.0.1",
					Port: 18600,
				},
			}, nil
		},
		BuildStartupContext: func(projectRoot string, startupSource string) (app.StartupContext, error) {
			return app.StartupContext{
				ProjectRoot:   projectRoot,
				StartupSource: startupSource,
				InstanceName:  "instance-name",
			}, nil
		},
		AcquireInstanceLock: func(name string) (app.InstanceLock, bool, error) {
			return stubLock{}, true, nil
		},
		LoadState: func(projectRoot string) (state.RuntimeState, error) {
			return state.RuntimeState{}, nil
		},
		SaveState: func(projectRoot string, runtimeState state.RuntimeState) (string, error) {
			return "", nil
		},
		StartOwnedProcessGroup: func(ctx context.Context, cfg config.Config) (app.OwnedProcessGroup, error) {
			return stubOwnedProcessGroup{}, nil
		},
		EnsureBackend: func(ctx context.Context, cfg config.Config, previous state.RuntimeState, session *control.Session) (supervisor.BackendResult, error) {
			if session == nil {
				t.Fatal("EnsureBackend owner session = nil, want control session")
			}
			copied := *session
			ownerSession = &copied
			return supervisor.BackendResult{
				State: state.RuntimeState{
					Backend: state.BackendState{
						Mode:   "owned",
						PID:    24680,
						Port:   18600,
						Origin: "http://127.0.0.1:18600",
					},
					LastPhase: app.PhaseBackendReady,
				},
			}, nil
		},
		StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error) {
			return supervisor.FrontendResult{
				State: state.RuntimeState{
					FrontendHost: state.FrontendHostState{
						Kind:   "vite",
						PID:    97531,
						Port:   5175,
						Origin: "http://localhost:5175",
					},
					LastPhase: app.PhaseRunning,
				},
			}, nil
		},
		WaitForSupervisor: func(ctx context.Context, cfg config.Config, current state.RuntimeState, backendResult supervisor.BackendResult, frontendResult supervisor.FrontendResult) error {
			if ownerSession == nil {
				t.Fatal("ownerSession = nil, want session captured from EnsureBackend")
			}

			body, err := json.Marshal(map[string]string{"source": "test"})
			if err != nil {
				t.Fatalf("Marshal request body: %v", err)
			}

			request, err := http.NewRequest(http.MethodPost, ownerSession.ControlOrigin+"/v1/control/shutdown", bytes.NewReader(body))
			if err != nil {
				t.Fatalf("NewRequest returned error: %v", err)
			}
			request.Header.Set("Authorization", "Bearer "+ownerSession.ControlToken)
			request.Header.Set("Content-Type", "application/json")

			response, err := (&http.Client{Timeout: time.Second}).Do(request)
			if err != nil {
				t.Fatalf("shutdown request returned error: %v", err)
			}
			defer response.Body.Close()

			if response.StatusCode != http.StatusAccepted {
				t.Fatalf("StatusCode = %d, want 202", response.StatusCode)
			}

			select {
			case <-ctx.Done():
				return nil
			case <-time.After(time.Second):
				t.Fatal("supervisor context was not cancelled after shutdown request")
				return nil
			}
		},
	})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
}

type stubOwnerControlHandle struct {
	session control.Session
}

func (s stubOwnerControlHandle) Session() control.Session {
	return s.session
}

func (stubOwnerControlHandle) Close() error {
	return nil
}

type stubOwnedProcessGroup struct{}

func (stubOwnedProcessGroup) Attach(pid int) error {
	return nil
}

func (stubOwnedProcessGroup) Close() error {
	return nil
}
