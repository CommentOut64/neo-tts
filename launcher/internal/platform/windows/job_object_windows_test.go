package windows

import (
	"runtime"
	"syscall"
	"testing"
	"unsafe"
)

func TestAttachOwnedProcessToJobObjectConfiguresKillOnClose(t *testing.T) {
	info := buildOwnedProcessJobObjectInfo()

	if info.BasicLimitInformation.LimitFlags&jobObjectLimitKillOnJobClose == 0 {
		t.Fatalf("LimitFlags = %#x, want kill-on-close flag", info.BasicLimitInformation.LimitFlags)
	}
}

func TestOwnedProcessAccessRightsIncludeTerminate(t *testing.T) {
	access := ownedProcessAccessRights()

	if access&processSetQuota == 0 {
		t.Fatalf("access rights = %#x, want PROCESS_SET_QUOTA", access)
	}
	if access&processTerminate == 0 {
		t.Fatalf("access rights = %#x, want PROCESS_TERMINATE", access)
	}
}

func TestJobObjectExtendedLimitInformationMatchesWindowsABI(t *testing.T) {
	var basic jobObjectBasicLimitInformation
	var extended jobObjectExtendedLimitInformation

	wantBasicSize, wantExtendedSize := expectedJobObjectStructSizes()

	if unsafe.Sizeof(basic) != wantBasicSize {
		t.Fatalf("basic limit info size = %d, want %d", unsafe.Sizeof(basic), wantBasicSize)
	}
	if unsafe.Sizeof(extended) != wantExtendedSize {
		t.Fatalf("extended limit info size = %d, want %d", unsafe.Sizeof(extended), wantExtendedSize)
	}
}

func TestCreateOwnedProcessJobObjectDoesNotReturnBadLength(t *testing.T) {
	job, err := CreateOwnedProcessJobObject()
	if err != nil {
		if errno, ok := err.(syscall.Errno); ok && errno == syscall.Errno(24) {
			t.Fatalf("CreateOwnedProcessJobObject returned ERROR_BAD_LENGTH: %v", err)
		}
		t.Fatalf("CreateOwnedProcessJobObject returned error: %v", err)
	}
	if job == nil {
		t.Fatal("CreateOwnedProcessJobObject returned nil job without error")
	}
	defer func() {
		if closeErr := job.Close(); closeErr != nil {
			t.Fatalf("Close returned error: %v", closeErr)
		}
	}()
}

func expectedJobObjectStructSizes() (uintptr, uintptr) {
	switch runtime.GOARCH {
	case "386":
		return 48, 112
	case "amd64":
		return 64, 144
	default:
		panic("unsupported GOARCH in job object ABI test: " + runtime.GOARCH)
	}
}
