package windows

import (
	"crypto/sha1"
	"encoding/hex"
	"syscall"
	"unsafe"
)

var (
	modKernel32      = syscall.NewLazyDLL("kernel32.dll")
	procCreateMutexW = modKernel32.NewProc("CreateMutexW")
	procReleaseMutex = modKernel32.NewProc("ReleaseMutex")
	procCloseHandle  = modKernel32.NewProc("CloseHandle")
)

const errorAlreadyExists syscall.Errno = 183

type InstanceLock struct {
	handle syscall.Handle
}

func InstanceName(projectRoot string) string {
	sum := sha1.Sum([]byte(projectRoot))
	return `Global\neo-tts-launcher-` + hex.EncodeToString(sum[:8])
}

func TryAcquireInstanceLock(name string) (*InstanceLock, bool, error) {
	namePtr, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return nil, false, err
	}

	handle, _, callErr := procCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(namePtr)))
	if handle == 0 {
		if callErr != syscall.Errno(0) {
			return nil, false, callErr
		}
		return nil, false, syscall.EINVAL
	}

	lock := &InstanceLock{handle: syscall.Handle(handle)}
	if callErr == errorAlreadyExists {
		return lock, false, nil
	}
	return lock, true, nil
}

func (lock *InstanceLock) Close() error {
	if lock == nil || lock.handle == 0 {
		return nil
	}
	procReleaseMutex.Call(uintptr(lock.handle))
	procCloseHandle.Call(uintptr(lock.handle))
	lock.handle = 0
	return nil
}
