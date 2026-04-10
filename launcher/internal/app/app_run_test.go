package app_test

import (
	"context"
	"errors"
	"reflect"
	"testing"

	app "neo-tts/launcher/internal/app"
	"neo-tts/launcher/internal/config"
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
		EnsureBackend: func(ctx context.Context, cfg config.Config, previous state.RuntimeState) (supervisor.BackendResult, error) {
			order = append(order, "backend")
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
						Origin:        "http://127.0.0.1:5175",
						Command:       "npm run dev",
						BrowserOpened: true,
					},
					LastPhase: app.PhaseRunning,
				},
			}, nil
		},
		WaitForSupervisor: func(ctx context.Context, cfg config.Config, current state.RuntimeState) error {
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
					Origin: "http://127.0.0.1:5175",
				},
			}, nil
		},
		IsExistingWebInstanceHealthy: func(ctx context.Context, existing state.RuntimeState) bool {
			order = append(order, "existing-healthy")
			return true
		},
		EnsureBackend: func(ctx context.Context, cfg config.Config, previous state.RuntimeState) (supervisor.BackendResult, error) {
			return supervisor.BackendResult{}, errors.New("EnsureBackend should not be called")
		},
		StartFrontend: func(ctx context.Context, cfg config.Config, current state.RuntimeState) (supervisor.FrontendResult, error) {
			return supervisor.FrontendResult{}, errors.New("StartFrontend should not be called")
		},
		WaitForSupervisor: func(ctx context.Context, cfg config.Config, current state.RuntimeState) error {
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
