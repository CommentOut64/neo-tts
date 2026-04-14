package main

import (
	"context"
	"os"
	"reflect"
	"syscall"
	"testing"

	"neo-tts/launcher/internal/logging"
)

func TestNewRootContextSubscribesToInterruptAndSigterm(t *testing.T) {
	var gotSignals []os.Signal

	ctx, cancel := newRootContext(context.Background(), func(parent context.Context, signals ...os.Signal) (context.Context, context.CancelFunc) {
		gotSignals = append(gotSignals, signals...)
		return parent, func() {}
	})
	defer cancel()

	if ctx == nil {
		t.Fatal("ctx = nil, want context")
	}
	want := []os.Signal{os.Interrupt, syscall.SIGTERM}
	if !reflect.DeepEqual(gotSignals, want) {
		t.Fatalf("signals = %#v, want %#v", gotSignals, want)
	}
}

func TestBuildBootstrapContextIncludesElevationAndSource(t *testing.T) {
	got := buildBootstrapContext(`F:\neo-tts`, `F:\neo-tts\launcher.exe`, []string{"--runtime-mode", "dev"}, "double-click", true)

	want := logging.StartupContext{
		WorkingDirectory: `F:\neo-tts`,
		ExecutablePath:   `F:\neo-tts\launcher.exe`,
		Arguments:        []string{"--runtime-mode", "dev"},
		IsElevated:       true,
		StartupSource:    "double-click",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("buildBootstrapContext = %#v, want %#v", got, want)
	}
}
