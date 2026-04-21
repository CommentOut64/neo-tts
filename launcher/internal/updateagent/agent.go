package updateagent

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
)

type Options struct {
	PlanPath     string
	BootstrapPID int
}

type Plan struct {
	SchemaVersion          int      `json:"schemaVersion"`
	BootstrapSourcePath    string   `json:"bootstrapSourcePath"`
	BootstrapTargetPath    string   `json:"bootstrapTargetPath"`
	UpdateAgentSourcePath  string   `json:"updateAgentSourcePath,omitempty"`
	UpdateAgentTargetPath  string   `json:"updateAgentTargetPath,omitempty"`
	RelaunchExecutablePath string   `json:"relaunchExecutablePath"`
	RelaunchArguments      []string `json:"relaunchArguments,omitempty"`
	RelaunchWorkingDirectory string `json:"relaunchWorkingDirectory"`
}

func ParseOptions(args []string) (Options, error) {
	flagSet := flag.NewFlagSet("update-agent", flag.ContinueOnError)
	flagSet.SetOutput(io.Discard)

	var options Options
	flagSet.StringVar(&options.PlanPath, "plan", "", "path to agent-plan.json")
	flagSet.IntVar(&options.BootstrapPID, "bootstrap-pid", 0, "pid of the bootstrap process to wait for")

	if err := flagSet.Parse(args); err != nil {
		return Options{}, err
	}
	if options.PlanPath == "" {
		return Options{}, fmt.Errorf("update-agent plan path is required")
	}
	if options.BootstrapPID <= 0 {
		return Options{}, fmt.Errorf("update-agent bootstrap pid must be positive")
	}
	return options, nil
}

func LoadPlan(path string) (Plan, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return Plan{}, err
	}

	var plan Plan
	decoder := json.NewDecoder(bytes.NewReader(content))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&plan); err != nil {
		return Plan{}, err
	}
	if err := plan.Validate(); err != nil {
		return Plan{}, err
	}
	return plan, nil
}

func (plan Plan) Validate() error {
	if plan.SchemaVersion != 1 {
		return fmt.Errorf("unsupported agent plan schema version: %d", plan.SchemaVersion)
	}
	if plan.BootstrapSourcePath == "" {
		return fmt.Errorf("agent plan bootstrapSourcePath is required")
	}
	if plan.BootstrapTargetPath == "" {
		return fmt.Errorf("agent plan bootstrapTargetPath is required")
	}
	if plan.RelaunchExecutablePath == "" {
		return fmt.Errorf("agent plan relaunchExecutablePath is required")
	}
	if plan.RelaunchWorkingDirectory == "" {
		return fmt.Errorf("agent plan relaunchWorkingDirectory is required")
	}
	if (plan.UpdateAgentSourcePath == "") != (plan.UpdateAgentTargetPath == "") {
		return fmt.Errorf("agent plan update-agent paths must be set together")
	}
	return nil
}
