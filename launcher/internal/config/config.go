package config

import (
	"bufio"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type Config struct {
	ProjectRoot   string
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
	RuntimeMode  string
	FrontendMode string
}

type launcherJSON struct {
	RuntimeMode  string          `json:"runtimeMode"`
	FrontendMode string          `json:"frontendMode"`
	Backend      backendJSONFile `json:"backend"`
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

	if err := mergeLauncherJSON(&cfg, filepath.Join(projectRoot, "launcher", "launcher.json")); err != nil {
		return Config{}, err
	}
	if err := mergeDotEnv(&cfg, filepath.Join(projectRoot, ".env")); err != nil {
		return Config{}, err
	}
	mergeCLIOverrides(&cfg, overrides)

	return cfg, nil
}

func defaultConfig(projectRoot string) Config {
	return Config{
		ProjectRoot:   projectRoot,
		RuntimeMode:   "dev",
		FrontendMode:  "web",
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

func mergeLauncherJSON(cfg *Config, path string) error {
	content, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}

	var parsed launcherJSON
	if err := json.Unmarshal(content, &parsed); err != nil {
		return err
	}

	if parsed.RuntimeMode != "" {
		cfg.RuntimeMode = parsed.RuntimeMode
	}
	if parsed.FrontendMode != "" {
		cfg.FrontendMode = parsed.FrontendMode
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

func mergeDotEnv(cfg *Config, path string) error {
	file, err := os.Open(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = trimEnvValue(strings.TrimSpace(value))

		switch key {
		case "LAUNCHER_RUNTIME_MODE":
			if value != "" {
				cfg.RuntimeMode = value
			}
		case "LAUNCHER_FRONTEND_MODE":
			if value != "" {
				cfg.FrontendMode = value
			}
		case "LAUNCHER_BACKEND_MODE":
			if value != "" {
				cfg.Backend.Mode = value
			}
		case "LAUNCHER_BACKEND_HOST":
			if value != "" {
				cfg.Backend.Host = value
			}
		case "LAUNCHER_BACKEND_PORT":
			if value != "" {
				cfg.Backend.Port = atoiOrDefault(value, cfg.Backend.Port)
			}
		case "LAUNCHER_BACKEND_DEV_PYTHON":
			if value != "" {
				cfg.Backend.DevPython = value
			}
		case "LAUNCHER_BACKEND_PRODUCT_PYTHON":
			if value != "" {
				cfg.Backend.ProductPython = value
			}
		case "LAUNCHER_BACKEND_EXTERNAL_ORIGIN":
			if value != "" {
				cfg.Backend.ExternalOrigin = value
			}
		}
	}

	return scanner.Err()
}

func mergeCLIOverrides(cfg *Config, overrides CLIOverrides) {
	if overrides.RuntimeMode != "" {
		cfg.RuntimeMode = overrides.RuntimeMode
	}
	if overrides.FrontendMode != "" {
		cfg.FrontendMode = overrides.FrontendMode
	}
}

func trimEnvValue(value string) string {
	if len(value) >= 2 {
		if strings.HasPrefix(value, "\"") && strings.HasSuffix(value, "\"") {
			return strings.Trim(value, "\"")
		}
		if strings.HasPrefix(value, "'") && strings.HasSuffix(value, "'") {
			return strings.Trim(value, "'")
		}
	}
	return value
}

func atoiOrDefault(value string, fallback int) int {
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}
