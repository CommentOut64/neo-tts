package bootstrap

import (
	"flag"
	"fmt"
	"io"
	"path/filepath"
)

type Options struct {
	RootDir       string
	Channel       string
	StartupSource string
}

func ParseOptions(args []string, executablePath string, workingDirectory string) (Options, error) {
	flagSet := flag.NewFlagSet("bootstrap", flag.ContinueOnError)
	flagSet.SetOutput(io.Discard)

	var rootDir string
	options := Options{
		Channel:       "stable",
		StartupSource: "direct",
	}
	flagSet.StringVar(&rootDir, "root", "", "bootstrap product root")
	flagSet.StringVar(&options.Channel, "channel", options.Channel, "update channel")
	flagSet.StringVar(&options.StartupSource, "startup-source", options.StartupSource, "bootstrap startup source")

	if err := flagSet.Parse(args); err != nil {
		return Options{}, err
	}
	if options.Channel == "" {
		return Options{}, fmt.Errorf("bootstrap channel cannot be empty")
	}
	if options.StartupSource == "" {
		return Options{}, fmt.Errorf("bootstrap startup source cannot be empty")
	}

	resolvedRoot, err := resolveRootDir(rootDir, executablePath, workingDirectory)
	if err != nil {
		return Options{}, err
	}
	options.RootDir = resolvedRoot
	return options, nil
}

func resolveRootDir(rootDir string, executablePath string, workingDirectory string) (string, error) {
	switch {
	case rootDir != "":
		if !filepath.IsAbs(rootDir) && workingDirectory != "" {
			rootDir = filepath.Join(workingDirectory, rootDir)
		}
	case executablePath != "":
		rootDir = filepath.Dir(executablePath)
	case workingDirectory != "":
		rootDir = workingDirectory
	default:
		return "", fmt.Errorf("bootstrap root could not be resolved")
	}

	absoluteRoot, err := filepath.Abs(rootDir)
	if err != nil {
		return "", err
	}
	return filepath.Clean(absoluteRoot), nil
}
