package main

import (
	"context"
	"flag"
	"os"
	"os/signal"
	"syscall"
	"time"

	"neo-tts/launcher/internal/app"
	"neo-tts/launcher/internal/config"
	"neo-tts/launcher/internal/logging"
	winplatform "neo-tts/launcher/internal/platform/windows"
)

type signalContextFactory func(parent context.Context, signals ...os.Signal) (context.Context, context.CancelFunc)

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

	isElevated, _ := winplatform.IsCurrentProcessElevated()
	session, _ := logging.Bootstrap(projectRoot, buildBootstrapContext(projectRoot, executablePath, os.Args[1:], *startupSource, isElevated))

	cfg, err := config.Load(projectRoot, config.CLIOverrides{
		RuntimeMode:  *runtimeMode,
		FrontendMode: *frontendMode,
	})
	if err == nil {
		if consoleErr := winplatform.EnsureConsoleMode(winplatform.ResolveConsoleMode(cfg.RuntimeMode)); consoleErr == nil && cfg.RuntimeMode == "dev" {
			_ = winplatform.SetConsoleTitle(winplatform.BuildConsoleTitle(projectRoot, cfg.RuntimeMode, cfg.FrontendMode))
		}
	}

	rootCtx, stop := newRootContext(context.Background(), signal.NotifyContext)
	defer stop()
	shutdownDone := make(chan struct{})
	defer close(shutdownDone)
	if cfg.RuntimeMode == "dev" {
		removeConsoleHandler, handlerErr := winplatform.InstallConsoleCloseHandler(stop, shutdownDone, 2*time.Second)
		if handlerErr == nil {
			defer removeConsoleHandler()
		}
	}

	_, err = app.Run(rootCtx, app.RunOptions{
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

func newRootContext(parent context.Context, factory signalContextFactory) (context.Context, context.CancelFunc) {
	if factory == nil {
		factory = signal.NotifyContext
	}
	return factory(parent, os.Interrupt, syscall.SIGTERM)
}

func buildBootstrapContext(
	projectRoot string,
	executablePath string,
	args []string,
	startupSource string,
	isElevated bool,
) logging.StartupContext {
	return logging.StartupContext{
		WorkingDirectory: projectRoot,
		ExecutablePath:   executablePath,
		Arguments:        args,
		IsElevated:       isElevated,
		StartupSource:    startupSource,
	}
}
