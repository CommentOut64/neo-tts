package app

import (
	"context"
	"errors"
	"testing"

	"neo-tts/launcher/internal/config"
)

func TestInstanceNameDependsOnProjectRoot(t *testing.T) {
	nameA := BuildInstanceName(`F:\neo-tts`)
	nameB := BuildInstanceName(`F:\neo-tts-copy`)

	if nameA == "" {
		t.Fatal("nameA is empty")
	}
	if nameB == "" {
		t.Fatal("nameB is empty")
	}
	if nameA == nameB {
		t.Fatalf("BuildInstanceName returned same value for different roots: %q", nameA)
	}
}

func TestStartupContextCapturesElevationAndSource(t *testing.T) {
	ctx, err := BuildStartupContext(`F:\neo-tts`, "double-click")
	if err != nil {
		t.Fatalf("BuildStartupContext returned error: %v", err)
	}

	if ctx.ProjectRoot != `F:\neo-tts` {
		t.Fatalf("ProjectRoot = %q, want F:\\neo-tts", ctx.ProjectRoot)
	}
	if ctx.StartupSource != "double-click" {
		t.Fatalf("StartupSource = %q, want double-click", ctx.StartupSource)
	}
	if ctx.InstanceName == "" {
		t.Fatal("InstanceName is empty")
	}
}

func TestRunRejectsNonDevWebLauncherProfile(t *testing.T) {
	_, err := Run(context.Background(), RunOptions{
		ProjectRoot: `F:\neo-tts`,
	}, AppDeps{
		LoadConfig: func(projectRoot string, overrides config.CLIOverrides) (config.Config, error) {
			return config.Config{
				ProjectRoot:  projectRoot,
				Profile:      config.ProfileProductElectron,
				RuntimeMode:  "product",
				FrontendMode: "electron",
			}, nil
		},
	})
	if !errors.Is(err, ErrUnsupportedLauncherProfile) {
		t.Fatalf("Run error = %v, want ErrUnsupportedLauncherProfile", err)
	}
}
