package httpcheck

import (
	"context"
	"strings"
	"testing"
	"time"

	winplatform "neo-tts/launcher/internal/platform/windows"
)

func TestBuildPowerShellCommandPreservesWorkingDirAndEnv(t *testing.T) {
	invocation := winplatform.BuildPowerShellInvocation(winplatform.ProcessSpec{
		Command:          "npm run dev",
		WorkingDirectory: `F:\neo-tts\frontend`,
		Environment: map[string]string{
			"VITE_BACKEND_ORIGIN": "http://127.0.0.1:18600",
		},
	})

	if invocation.Executable != "powershell" {
		t.Fatalf("Executable = %q, want powershell", invocation.Executable)
	}
	if invocation.WorkingDirectory != `F:\neo-tts\frontend` {
		t.Fatalf("WorkingDirectory = %q, want F:\\neo-tts\\frontend", invocation.WorkingDirectory)
	}
	if strings.Join(invocation.Args, " ") == "" {
		t.Fatal("Args is empty")
	}
	found := false
	for _, item := range invocation.Environment {
		if item == "VITE_BACKEND_ORIGIN=http://127.0.0.1:18600" {
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("Environment missing VITE_BACKEND_ORIGIN: %+v", invocation.Environment)
	}
}

func TestWaitForHealthReturnsErrorOnTimeout(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()

	err := WaitForHealthy(ctx, "http://127.0.0.1:65534/health", 25*time.Millisecond)
	if err == nil {
		t.Fatal("WaitForHealthy returned nil, want timeout or probe error")
	}
}
