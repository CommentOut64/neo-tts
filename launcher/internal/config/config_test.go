package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadConfigDefaultsToOwnedDevWebProfile(t *testing.T) {
	projectRoot := t.TempDir()

	cfg, err := Load(projectRoot, CLIOverrides{})
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if cfg.Profile != ProfileDevWeb {
		t.Fatalf("Profile = %q, want %q", cfg.Profile, ProfileDevWeb)
	}
	if cfg.RuntimeMode != "dev" {
		t.Fatalf("RuntimeMode = %q, want dev", cfg.RuntimeMode)
	}
	if cfg.FrontendMode != "web" {
		t.Fatalf("FrontendMode = %q, want web", cfg.FrontendMode)
	}
	if cfg.Backend.Mode != "owned" {
		t.Fatalf("Backend.Mode = %q, want owned", cfg.Backend.Mode)
	}
	if cfg.Backend.Port != 18600 {
		t.Fatalf("Backend.Port = %d, want 18600", cfg.Backend.Port)
	}
}

func TestProcessEnvOverridesLaunchJSON(t *testing.T) {
	projectRoot := t.TempDir()
	writeFile(t, filepath.Join(projectRoot, "config", "launch.json"), `{
  "profile": "product-electron",
  "backend": {
    "mode": "external",
    "port": 19000
  }
}`)
	t.Setenv("LAUNCHER_PROFILE", "dev-web")
	t.Setenv("LAUNCHER_BACKEND_MODE", "owned")
	t.Setenv("LAUNCHER_BACKEND_PORT", "18600")

	cfg, err := Load(projectRoot, CLIOverrides{})
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if cfg.Profile != ProfileDevWeb {
		t.Fatalf("Profile = %q, want %q", cfg.Profile, ProfileDevWeb)
	}
	if cfg.RuntimeMode != "dev" {
		t.Fatalf("RuntimeMode = %q, want dev", cfg.RuntimeMode)
	}
	if cfg.FrontendMode != "web" {
		t.Fatalf("FrontendMode = %q, want web", cfg.FrontendMode)
	}
	if cfg.Backend.Mode != "owned" {
		t.Fatalf("Backend.Mode = %q, want owned", cfg.Backend.Mode)
	}
	if cfg.Backend.Port != 18600 {
		t.Fatalf("Backend.Port = %d, want 18600", cfg.Backend.Port)
	}
}

func TestCLIOverridesProcessEnv(t *testing.T) {
	projectRoot := t.TempDir()
	t.Setenv("LAUNCHER_PROFILE", "dev-web")

	cfg, err := Load(projectRoot, CLIOverrides{
		Profile: ProfileProductElectron,
	})
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if cfg.Profile != ProfileProductElectron {
		t.Fatalf("Profile = %q, want %q", cfg.Profile, ProfileProductElectron)
	}
	if cfg.RuntimeMode != "product" {
		t.Fatalf("RuntimeMode = %q, want product", cfg.RuntimeMode)
	}
	if cfg.FrontendMode != "electron" {
		t.Fatalf("FrontendMode = %q, want electron", cfg.FrontendMode)
	}
}

func TestExternalBackendSkipsOwnedCommandRequirement(t *testing.T) {
	projectRoot := t.TempDir()
	t.Setenv("LAUNCHER_BACKEND_MODE", "external")
	t.Setenv("LAUNCHER_BACKEND_EXTERNAL_ORIGIN", "http://127.0.0.1:18600")

	cfg, err := Load(projectRoot, CLIOverrides{})
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	if cfg.Backend.Mode != "external" {
		t.Fatalf("Backend.Mode = %q, want external", cfg.Backend.Mode)
	}
	if cfg.Backend.ExternalOrigin != "http://127.0.0.1:18600" {
		t.Fatalf("Backend.ExternalOrigin = %q, want http://127.0.0.1:18600", cfg.Backend.ExternalOrigin)
	}
}

func TestProductDefaultsToRuntimePython(t *testing.T) {
	projectRoot := t.TempDir()

	cfg, err := Load(projectRoot, CLIOverrides{
		RuntimeMode: "product",
	})
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	want := filepath.Join("runtime", "python", "python.exe")
	if cfg.Backend.ProductPython != want {
		t.Fatalf("Backend.ProductPython = %q, want %q", cfg.Backend.ProductPython, want)
	}
}

func TestRejectsUnsupportedProductWebProfile(t *testing.T) {
	projectRoot := t.TempDir()

	_, err := Load(projectRoot, CLIOverrides{
		RuntimeMode:  "product",
		FrontendMode: "web",
	})
	if err == nil {
		t.Fatal("Load returned nil error, want unsupported product/web profile")
	}
}

func TestRejectsUnsupportedDevElectronProfile(t *testing.T) {
	projectRoot := t.TempDir()
	writeFile(t, filepath.Join(projectRoot, "config", "launch.json"), `{
  "profile": "product-electron"
}`)

	_, err := Load(projectRoot, CLIOverrides{
		RuntimeMode: "dev",
	})
	if err == nil {
		t.Fatal("Load returned nil error, want unsupported dev/electron profile")
	}
}

func writeFile(t *testing.T, path string, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("MkdirAll(%q): %v", path, err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("WriteFile(%q): %v", path, err)
	}
}
