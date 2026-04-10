package main

import (
	"context"
	"flag"
	"os"

	"neo-tts/launcher/internal/app"
	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/logging"
	winplatform "neo-tts/launcher/internal/platform/windows"
)

func main() {
	runtimeMode := flag.String("runtime-mode", "", "launcher runtime mode")
	frontendMode := flag.String("frontend-mode", "", "launcher frontend mode")
	startupSource := flag.String("startup-source", "direct", "launcher startup source")
	flag.Parse()

	projectRoot, err := os.Getwd()
	if err != nil {
		projectRoot = "."
	}

	executablePath, err := os.Executable()
	if err != nil {
		executablePath = os.Args[0]
	}

	session, _ := logging.Bootstrap(projectRoot, logging.StartupContext{
		WorkingDirectory: projectRoot,
		ExecutablePath:   executablePath,
		Arguments:        os.Args[1:],
		StartupSource:    *startupSource,
	})

	cfg, err := config.Load(projectRoot, config.CLIOverrides{
		RuntimeMode:  *runtimeMode,
		FrontendMode: *frontendMode,
	})
	if err == nil {
		_ = winplatform.EnsureConsoleMode(winplatform.ResolveConsoleMode(cfg.RuntimeMode))
	}

	_, err = app.Run(context.Background(), app.RunOptions{
		ProjectRoot: projectRoot,
		Overrides: config.CLIOverrides{
			RuntimeMode:  *runtimeMode,
			FrontendMode: *frontendMode,
		},
		StartupSource: *startupSource,
		LogFilePath:   session.LogFilePath,
	}, app.AppDeps{})
	if err != nil {
		os.Exit(1)
	}
}
