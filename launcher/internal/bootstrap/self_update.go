package bootstrap

import (
	"encoding/json"
	"path/filepath"

	"neo-tts/launcher/internal/updateagent"
)

func BuildSelfUpdatePlan(rootDir string, candidate CurrentState) (updateagent.Plan, error) {
	bootstrapRoot, err := ResolvePackageRoot(rootDir, candidate, "bootstrap")
	if err != nil {
		return updateagent.Plan{}, err
	}

	plan := updateagent.Plan{
		SchemaVersion:            1,
		BootstrapSourcePath:      filepath.Join(bootstrapRoot, "NeoTTS.exe"),
		BootstrapTargetPath:      filepath.Join(filepath.Clean(rootDir), "NeoTTS.exe"),
		RelaunchExecutablePath:   filepath.Join(filepath.Clean(rootDir), "NeoTTS.exe"),
		RelaunchWorkingDirectory: filepath.Clean(rootDir),
		RelaunchArguments:        []string{"--startup-source", "update-agent"},
	}

	if _, ok := candidate.Packages["update-agent"]; ok {
		updateAgentRoot, err := ResolvePackageRoot(rootDir, candidate, "update-agent")
		if err != nil {
			return updateagent.Plan{}, err
		}
		plan.UpdateAgentSourcePath = filepath.Join(updateAgentRoot, "NeoTTSUpdateAgent.exe")
		plan.UpdateAgentTargetPath = filepath.Join(filepath.Clean(rootDir), "NeoTTSUpdateAgent.exe")
	}
	return plan, nil
}

func SaveSelfUpdatePlan(rootDir string, plan updateagent.Plan) (string, error) {
	planPath := filepath.Join(filepath.Clean(rootDir), "state", "agent-plan.json")
	_, err := writeJSONAtomic(planPath, plan)
	return planPath, err
}

func MarshalSelfUpdatePlan(plan updateagent.Plan) ([]byte, error) {
	return json.Marshal(plan)
}

func RequiresBootstrapSelfUpdate(current CurrentState, candidate CurrentState) bool {
	return packageVersionChanged(current, candidate, "bootstrap") || packageVersionChanged(current, candidate, "update-agent")
}

func packageVersionChanged(current CurrentState, candidate CurrentState, packageID string) bool {
	currentPackage, currentOK := current.Packages[packageID]
	candidatePackage, candidateOK := candidate.Packages[packageID]
	switch {
	case !currentOK && !candidateOK:
		return false
	case !currentOK || !candidateOK:
		return true
	default:
		return currentPackage.Version != candidatePackage.Version
	}
}
