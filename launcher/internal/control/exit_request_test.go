package control

import (
	"path/filepath"
	"testing"
)

func TestReadExitRequestReturnsNilWhenMissing(t *testing.T) {
	projectRoot := t.TempDir()

	request, err := ReadExitRequest(projectRoot)
	if err != nil {
		t.Fatalf("ReadExitRequest returned error: %v", err)
	}
	if request != nil {
		t.Fatalf("ReadExitRequest returned %+v, want nil", request)
	}
}

func TestWriteExitRequestRoundTripsSavedPayload(t *testing.T) {
	projectRoot := t.TempDir()
	want := ExitRequest{
		Kind:        "user_exit",
		Source:      "frontend",
		RequestedAt: "2026-04-11T22:00:00+08:00",
		LauncherPID: 12345,
	}

	path, err := WriteExitRequest(projectRoot, want)
	if err != nil {
		t.Fatalf("WriteExitRequest returned error: %v", err)
	}
	if path != filepath.Join(projectRoot, "logs", "launcher", "control", "exit-request.json") {
		t.Fatalf("WriteExitRequest path = %q", path)
	}

	got, err := ReadExitRequest(projectRoot)
	if err != nil {
		t.Fatalf("ReadExitRequest returned error: %v", err)
	}
	if got == nil {
		t.Fatal("ReadExitRequest returned nil, want payload")
	}
	if *got != want {
		t.Fatalf("ReadExitRequest = %+v, want %+v", *got, want)
	}
}

func TestDeleteExitRequestRemovesControlFile(t *testing.T) {
	projectRoot := t.TempDir()
	if _, err := WriteExitRequest(projectRoot, ExitRequest{
		Kind:        "user_exit",
		Source:      "frontend",
		RequestedAt: "2026-04-11T22:00:00+08:00",
		LauncherPID: 12345,
	}); err != nil {
		t.Fatalf("WriteExitRequest returned error: %v", err)
	}

	if err := DeleteExitRequest(projectRoot); err != nil {
		t.Fatalf("DeleteExitRequest returned error: %v", err)
	}

	request, err := ReadExitRequest(projectRoot)
	if err != nil {
		t.Fatalf("ReadExitRequest returned error: %v", err)
	}
	if request != nil {
		t.Fatalf("ReadExitRequest returned %+v, want nil after delete", request)
	}
}
