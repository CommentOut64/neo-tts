package logging

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type StartupContext struct {
	WorkingDirectory string
	ExecutablePath   string
	Arguments        []string
	IsElevated       bool
	StartupSource    string
}

type Session struct {
	LogFilePath string
}

func Bootstrap(projectRoot string, startup StartupContext) (Session, error) {
	logDir := filepath.Join(projectRoot, "logs", "launcher")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return Session{}, err
	}

	logFilePath := filepath.Join(
		logDir,
		fmt.Sprintf("launcher_%s_%d.log", time.Now().Format("20060102_150405"), os.Getpid()),
	)

	startupLine := fmt.Sprintf(
		"startup begin cwd=%s exe=%s args=%s elevated=%t source=%s\n",
		startup.WorkingDirectory,
		startup.ExecutablePath,
		strings.Join(startup.Arguments, " "),
		startup.IsElevated,
		startup.StartupSource,
	)

	if err := os.WriteFile(logFilePath, []byte(startupLine), 0o644); err != nil {
		return Session{}, err
	}

	return Session{LogFilePath: logFilePath}, nil
}

func Append(logFilePath string, line string) error {
	if logFilePath == "" {
		return nil
	}
	file, err := os.OpenFile(logFilePath, os.O_APPEND|os.O_WRONLY|os.O_CREATE, 0o644)
	if err != nil {
		return err
	}
	defer file.Close()

	if !strings.HasSuffix(line, "\n") {
		line += "\n"
	}
	_, err = file.WriteString(line)
	return err
}
