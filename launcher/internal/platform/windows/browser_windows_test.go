package windows

import (
	"errors"
	"strings"
	"testing"
)

func TestOpenBrowserPrefersShellExecute(t *testing.T) {
	originalShellExecute := shellExecuteURL
	originalFallback := startBrowserFallback
	defer func() {
		shellExecuteURL = originalShellExecute
		startBrowserFallback = originalFallback
	}()

	shellCalls := 0
	fallbackCalls := 0
	shellExecuteURL = func(url string) error {
		shellCalls++
		if url != "http://localhost:5175" {
			t.Fatalf("shellExecuteURL url = %q, want http://localhost:5175", url)
		}
		return nil
	}
	startBrowserFallback = func(url string) error {
		fallbackCalls++
		return nil
	}

	if err := OpenBrowser("http://localhost:5175"); err != nil {
		t.Fatalf("OpenBrowser returned error: %v", err)
	}
	if shellCalls != 1 {
		t.Fatalf("shellExecuteURL calls = %d, want 1", shellCalls)
	}
	if fallbackCalls != 0 {
		t.Fatalf("startBrowserFallback calls = %d, want 0", fallbackCalls)
	}
}

func TestOpenBrowserFallsBackWhenShellExecuteFails(t *testing.T) {
	originalShellExecute := shellExecuteURL
	originalFallback := startBrowserFallback
	defer func() {
		shellExecuteURL = originalShellExecute
		startBrowserFallback = originalFallback
	}()

	shellExecuteURL = func(url string) error {
		return errors.New("shell execute failed")
	}
	fallbackCalls := 0
	startBrowserFallback = func(url string) error {
		fallbackCalls++
		if url != "http://localhost:5175" {
			t.Fatalf("startBrowserFallback url = %q, want http://localhost:5175", url)
		}
		return nil
	}

	if err := OpenBrowser("http://localhost:5175"); err != nil {
		t.Fatalf("OpenBrowser returned error: %v", err)
	}
	if fallbackCalls != 1 {
		t.Fatalf("startBrowserFallback calls = %d, want 1", fallbackCalls)
	}
}

func TestBuildOpenBrowserInvocationUsesStartProcess(t *testing.T) {
	invocation := buildOpenBrowserInvocation("http://127.0.0.1:5175")

	if invocation.Executable != "cmd" {
		t.Fatalf("Executable = %q, want cmd", invocation.Executable)
	}
	text := strings.Join(invocation.Args, " ")
	if !strings.Contains(text, "start") {
		t.Fatalf("Args = %q, want cmd start", text)
	}
	if !strings.Contains(text, "http://127.0.0.1:5175") {
		t.Fatalf("Args = %q, want frontend url", text)
	}
}
