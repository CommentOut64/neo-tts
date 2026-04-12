package config

import "fmt"

type LaunchProfile string

const (
	ProfileDevWeb          LaunchProfile = "dev-web"
	ProfileProductElectron LaunchProfile = "product-electron"
)

func normalizeProfile(profile LaunchProfile) (LaunchProfile, string, string, error) {
	switch profile {
	case "":
		return "", "", "", nil
	case ProfileDevWeb:
		return ProfileDevWeb, "dev", "web", nil
	case ProfileProductElectron:
		return ProfileProductElectron, "product", "electron", nil
	default:
		return "", "", "", fmt.Errorf("unsupported launcher profile: %s", profile)
	}
}

func deriveProfile(runtimeMode string, frontendMode string) (LaunchProfile, error) {
	switch {
	case runtimeMode == "" && frontendMode == "":
		return "", nil
	case runtimeMode == "dev" && frontendMode == "web":
		return ProfileDevWeb, nil
	case runtimeMode == "product" && frontendMode == "electron":
		return ProfileProductElectron, nil
	default:
		return "", fmt.Errorf("unsupported launcher mode combination: %s/%s", runtimeMode, frontendMode)
	}
}
