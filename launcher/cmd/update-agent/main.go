package main

import (
	"fmt"
	"os"

	"neo-tts/launcher/internal/bootstrap"
	"neo-tts/launcher/internal/logging"
	"neo-tts/launcher/internal/updateagent"
)

func main() {
	options, err := updateagent.ParseOptions(os.Args[1:])
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	plan, err := updateagent.LoadPlan(options.PlanPath)
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	session, _ := logging.Bootstrap(plan.RelaunchWorkingDirectory, logging.StartupContext{
		WorkingDirectory: plan.RelaunchWorkingDirectory,
		ExecutablePath:   plan.RelaunchExecutablePath,
		Arguments:        os.Args[1:],
		StartupSource:    "update-agent",
	})
	if session.LogFilePath != "" {
		_ = logging.Append(session.LogFilePath, bootstrap.FormatLogEntry(
			"INFO",
			"update-agent",
			"update-agent loaded execution plan",
			map[string]any{
				"planPath":     options.PlanPath,
				"bootstrapPid": options.BootstrapPID,
			},
		))
	}
}
