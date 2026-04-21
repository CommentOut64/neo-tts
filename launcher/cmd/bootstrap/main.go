package main

import (
	"fmt"
	"os"

	"neo-tts/launcher/internal/bootstrap"
	"neo-tts/launcher/internal/logging"
	winplatform "neo-tts/launcher/internal/platform/windows"
)

func main() {
	workingDirectory, err := os.Getwd()
	if err != nil {
		workingDirectory = "."
	}

	executablePath, err := os.Executable()
	if err != nil {
		executablePath = os.Args[0]
	}

	options, err := bootstrap.ParseOptions(os.Args[1:], executablePath, workingDirectory)
	if err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}

	isElevated, _ := winplatform.IsCurrentProcessElevated()
	session, _ := logging.Bootstrap(options.RootDir, logging.StartupContext{
		WorkingDirectory: options.RootDir,
		ExecutablePath:   executablePath,
		Arguments:        os.Args[1:],
		IsElevated:       isElevated,
		StartupSource:    options.StartupSource,
	})
	if session.LogFilePath != "" {
		_ = logging.Append(session.LogFilePath, "bootstrap initialized channel="+options.Channel)
	}

	store := bootstrap.NewStateStore(options.RootDir)
	if _, err := store.LoadCurrent(); err != nil {
		_, _ = fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
