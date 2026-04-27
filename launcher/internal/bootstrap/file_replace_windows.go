package bootstrap

import (
	"errors"
	"os"
	"syscall"
	"unsafe"
)

var (
	replaceKernel32       = syscall.NewLazyDLL("kernel32.dll")
	procReplaceFileW      = replaceKernel32.NewProc("ReplaceFileW")
	procMoveFileExW       = replaceKernel32.NewProc("MoveFileExW")
)

const moveFileReplaceExisting = 0x1

func replaceFileAtomically(sourcePath string, targetPath string) error {
	if _, err := os.Stat(targetPath); errors.Is(err, os.ErrNotExist) {
		return os.Rename(sourcePath, targetPath)
	} else if err != nil {
		return err
	}

	targetPtr, err := syscall.UTF16PtrFromString(targetPath)
	if err != nil {
		return err
	}
	sourcePtr, err := syscall.UTF16PtrFromString(sourcePath)
	if err != nil {
		return err
	}

	if replaced, _, callErr := procReplaceFileW.Call(
		uintptr(unsafe.Pointer(targetPtr)),
		uintptr(unsafe.Pointer(sourcePtr)),
		0,
		0,
		0,
		0,
	); replaced != 0 {
		return nil
	} else if callErr != syscall.Errno(0) {
		return callErr
	}

	if moved, _, callErr := procMoveFileExW.Call(
		uintptr(unsafe.Pointer(sourcePtr)),
		uintptr(unsafe.Pointer(targetPtr)),
		moveFileReplaceExisting,
	); moved != 0 {
		return nil
	} else if callErr != syscall.Errno(0) {
		return callErr
	}

	return syscall.EINVAL
}
