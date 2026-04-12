package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
)

type Config struct {
	ProjectRoot   string
	Profile       LaunchProfile
	RuntimeMode   string
	FrontendMode  string
	StartupSource string
	Backend       BackendConfig
}

type BackendConfig struct {
	Mode           string
	Host           string
	Port           int
	ExternalOrigin string
	DevPython      string
	ProductPython  string
}

type CLIOverrides struct {
	Profile      LaunchProfile
	RuntimeMode  string
	FrontendMode string
}

type launchJSON struct {
	Profile string          `json:"profile"`
	Backend backendJSONFile `json:"backend"`
}

type backendJSONFile struct {
	Mode           string `json:"mode"`
	Host           string `json:"host"`
	Port           int    `json:"port"`
	ExternalOrigin string `json:"externalOrigin"`
	DevPython      string `json:"devPython"`
	ProductPython  string `json:"productPython"`
}

func Load(projectRoot string, overrides CLIOverrides) (Config, error) {
	cfg := defaultConfig(projectRoot)

	if err := mergeLaunchJSON(&cfg, filepath.Join(projectRoot, "config", "launch.json")); err != nil {
		return Config{}, err
	}
	mergeEnvironment(&cfg)
	mergeCLIOverrides(&cfg, overrides)
	if err := finalizeProfile(&cfg); err != nil {
		return Config{}, err
	}

	return cfg, nil
}

func defaultConfig(projectRoot string) Config {
	return Config{
		ProjectRoot:   projectRoot,
		StartupSource: "double-click",
		Backend: BackendConfig{
			Mode:          "owned",
			Host:          "127.0.0.1",
			Port:          18600,
			DevPython:     filepath.Join(".venv", "Scripts", "python.exe"),
			ProductPython: filepath.Join("runtime", "python", "python.exe"),
		},
	}
}

func mergeLaunchJSON(cfg *Config, path string) error {
	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}

	var parsed launchJSON
	if err := json.Unmarshal(content, &parsed); err != nil {
		return err
	}

	if parsed.Profile != "" {
		cfg.Profile = LaunchProfile(parsed.Profile)
	}
	if parsed.Backend.Mode != "" {
		cfg.Backend.Mode = parsed.Backend.Mode
	}
	if parsed.Backend.Host != "" {
		cfg.Backend.Host = parsed.Backend.Host
	}
	if parsed.Backend.Port != 0 {
		cfg.Backend.Port = parsed.Backend.Port
	}
	if parsed.Backend.ExternalOrigin != "" {
		cfg.Backend.ExternalOrigin = parsed.Backend.ExternalOrigin
	}
	if parsed.Backend.DevPython != "" {
		cfg.Backend.DevPython = parsed.Backend.DevPython
	}
	if parsed.Backend.ProductPython != "" {
		cfg.Backend.ProductPython = parsed.Backend.ProductPython
	}

	return nil
}

func mergeEnvironment(cfg *Config) {
	if value := os.Getenv("LAUNCHER_PROFILE"); value != "" {
		cfg.Profile = LaunchProfile(value)
	}
	if value := os.Getenv("LAUNCHER_RUNTIME_MODE"); value != "" {
		cfg.RuntimeMode = value
	}
	if value := os.Getenv("LAUNCHER_FRONTEND_MODE"); value != "" {
		cfg.FrontendMode = value
	}
	if value := os.Getenv("LAUNCHER_BACKEND_MODE"); value != "" {
		cfg.Backend.Mode = value
	}
	if value := os.Getenv("LAUNCHER_BACKEND_HOST"); value != "" {
		cfg.Backend.Host = value
	}
	if value := os.Getenv("LAUNCHER_BACKEND_PORT"); value != "" {
		cfg.Backend.Port = atoiOrDefault(value, cfg.Backend.Port)
	}
	if value := os.Getenv("LAUNCHER_BACKEND_DEV_PYTHON"); value != "" {
		cfg.Backend.DevPython = value
	}
	if value := os.Getenv("LAUNCHER_BACKEND_PRODUCT_PYTHON"); value != "" {
		cfg.Backend.ProductPython = value
	}
	if value := os.Getenv("LAUNCHER_BACKEND_EXTERNAL_ORIGIN"); value != "" {
		cfg.Backend.ExternalOrigin = value
	}
}

func mergeCLIOverrides(cfg *Config, overrides CLIOverrides) {
	if overrides.Profile != "" {
		cfg.Profile = overrides.Profile
	}
	if overrides.RuntimeMode != "" {
		cfg.RuntimeMode = overrides.RuntimeMode
	}
	if overrides.FrontendMode != "" {
		cfg.FrontendMode = overrides.FrontendMode
	}
}

func finalizeProfile(cfg *Config) error {
	if cfg == nil {
		return nil
	}

	if cfg.Profile == "" && cfg.RuntimeMode == "" && cfg.FrontendMode == "" {
		cfg.Profile = ProfileDevWeb
	}

	if cfg.Profile != "" {
		profile, runtimeMode, frontendMode, err := normalizeProfile(cfg.Profile)
		if err != nil {
			return err
		}
		if cfg.RuntimeMode != "" && cfg.RuntimeMode != runtimeMode {
			return fmt.Errorf("launcher profile %s conflicts with runtime mode %s", profile, cfg.RuntimeMode)
		}
		if cfg.FrontendMode != "" && cfg.FrontendMode != frontendMode {
			return fmt.Errorf("launcher profile %s conflicts with frontend mode %s", profile, cfg.FrontendMode)
		}
		cfg.Profile = profile
		cfg.RuntimeMode = runtimeMode
		cfg.FrontendMode = frontendMode
		return nil
	}

	switch {
	case cfg.RuntimeMode == "dev" && cfg.FrontendMode == "":
		cfg.FrontendMode = "web"
	case cfg.RuntimeMode == "product" && cfg.FrontendMode == "":
		cfg.FrontendMode = "electron"
	case cfg.RuntimeMode == "" && cfg.FrontendMode == "web":
		cfg.RuntimeMode = "dev"
	case cfg.RuntimeMode == "" && cfg.FrontendMode == "electron":
		cfg.RuntimeMode = "product"
	}

	profile, err := deriveProfile(cfg.RuntimeMode, cfg.FrontendMode)
	if err != nil {
		return err
	}
	cfg.Profile = profile
	return nil
}

func atoiOrDefault(value string, fallback int) int {
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}
