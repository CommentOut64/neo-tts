package windows

import (
	"testing"
	"time"
)

func TestBuildConsoleTitleIncludesModesAndProjectName(t *testing.T) {
	got := BuildConsoleTitle(`F:\neo-tts`, "dev", "web")

	want := "neo-tts launcher [dev/web]"
	if got != want {
		t.Fatalf("BuildConsoleTitle = %q, want %q", got, want)
	}
}

func TestApplyVirtualTerminalModeAddsFlag(t *testing.T) {
	got, changed := applyVirtualTerminalMode(0x0001)

	if !changed {
		t.Fatal("changed = false, want true")
	}
	if got != 0x0005 {
		t.Fatalf("mode = %#x, want %#x", got, uint32(0x0005))
	}
}

func TestApplyVirtualTerminalModeKeepsExistingFlag(t *testing.T) {
	got, changed := applyVirtualTerminalMode(enableVirtualTerminalProcessing)

	if changed {
		t.Fatal("changed = true, want false")
	}
	if got != enableVirtualTerminalProcessing {
		t.Fatalf("mode = %#x, want %#x", got, uint32(enableVirtualTerminalProcessing))
	}
}

func TestIsGracefulConsoleShutdownEvent(t *testing.T) {
	for _, ctrlType := range []uint32{ctrlCloseEvent, ctrlLogoffEvent, ctrlShutdownEvent} {
		if !isGracefulConsoleShutdownEvent(ctrlType) {
			t.Fatalf("ctrlType=%d, want true", ctrlType)
		}
	}
	for _, ctrlType := range []uint32{0, 1, 3, 4} {
		if isGracefulConsoleShutdownEvent(ctrlType) {
			t.Fatalf("ctrlType=%d, want false", ctrlType)
		}
	}
}

func TestWaitForConsoleShutdownReturnsAfterDone(t *testing.T) {
	done := make(chan struct{})
	close(done)

	start := time.Now()
	waitForConsoleShutdown(done, time.Second)

	if time.Since(start) > 100*time.Millisecond {
		t.Fatal("waitForConsoleShutdown blocked after done channel closed")
	}
}
