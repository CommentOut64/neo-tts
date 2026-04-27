package main

import (
	"testing"
	"time"
)

func TestStartupGPUProbeTimeoutAllowsColdDriverStartup(t *testing.T) {
	if startupGPUProbeTimeout != 10*time.Second {
		t.Fatalf("startupGPUProbeTimeout = %s, want 10s", startupGPUProbeTimeout)
	}
}
