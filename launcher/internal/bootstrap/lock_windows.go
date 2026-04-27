package bootstrap

import (
	"crypto/sha1"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

var (
	lockKernel32         = syscall.NewLazyDLL("kernel32.dll")
	procLockCreateMutexW = lockKernel32.NewProc("CreateMutexW")
	procLockReleaseMutex = lockKernel32.NewProc("ReleaseMutex")
	procLockCloseHandle  = lockKernel32.NewProc("CloseHandle")
)

const updateLockAlreadyExists syscall.Errno = 183

type UpdateLockMetadata struct {
	OwnerPID   int       `json:"ownerPid"`
	SessionID  string    `json:"sessionId"`
	Phase      string    `json:"phase"`
	AcquiredAt time.Time `json:"acquiredAt"`
}

type UpdateLock struct {
	handle          syscall.Handle
	diagnosticsPath string
}

func UpdateMutexName(rootDir string) string {
	normalizedRoot := normalizeRootForLock(rootDir)
	sum := sha1.Sum([]byte(normalizedRoot))
	return `Local\NeoTTS.Update.` + hex.EncodeToString(sum[:8])
}

func TryAcquireUpdateLock(rootDir string, metadata UpdateLockMetadata) (*UpdateLock, bool, error) {
	namePtr, err := syscall.UTF16PtrFromString(UpdateMutexName(rootDir))
	if err != nil {
		return nil, false, err
	}

	handle, _, callErr := procLockCreateMutexW.Call(0, 1, uintptr(unsafe.Pointer(namePtr)))
	if handle == 0 {
		if callErr != syscall.Errno(0) {
			return nil, false, callErr
		}
		return nil, false, syscall.EINVAL
	}

	if callErr == updateLockAlreadyExists {
		procLockCloseHandle.Call(handle)
		return nil, false, nil
	}

	if metadata.OwnerPID == 0 {
		metadata.OwnerPID = os.Getpid()
	}
	if metadata.AcquiredAt.IsZero() {
		metadata.AcquiredAt = time.Now().UTC()
	}

	store := NewStateStore(rootDir)
	lock := &UpdateLock{
		handle:          syscall.Handle(handle),
		diagnosticsPath: store.UpdateLockPath(),
	}
	if _, err := writeJSONAtomic(lock.diagnosticsPath, metadata); err != nil {
		_ = lock.Close()
		return nil, false, err
	}

	return lock, true, nil
}

func (lock *UpdateLock) Close() error {
	if lock == nil || lock.handle == 0 {
		return nil
	}
	procLockReleaseMutex.Call(uintptr(lock.handle))
	procLockCloseHandle.Call(uintptr(lock.handle))
	lock.handle = 0
	if lock.diagnosticsPath != "" {
		_ = os.Remove(lock.diagnosticsPath)
	}
	return nil
}

func normalizeRootForLock(rootDir string) string {
	absoluteRoot, err := filepath.Abs(rootDir)
	if err != nil {
		absoluteRoot = rootDir
	}
	cleaned := filepath.Clean(absoluteRoot)
	cleaned = strings.TrimRight(cleaned, `\/`)
	return strings.ToLower(cleaned)
}
