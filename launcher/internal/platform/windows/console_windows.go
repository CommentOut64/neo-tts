package windows

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"time"
	"unsafe"
)

type ConsoleMode string

const (
	ConsoleVisible ConsoleMode = "visible"
	ConsoleHidden  ConsoleMode = "hidden"
)

const (
	attachParentProcess             = ^uintptr(0)
	stdOutputHandle                 = ^uintptr(10)
	stdErrorHandle                  = ^uintptr(11)
	enableVirtualTerminalProcessing = 0x0004
	ctrlCloseEvent                  = 2
	ctrlLogoffEvent                 = 5
	ctrlShutdownEvent               = 6
)

var (
	procAllocConsole  = modKernel32.NewProc("AllocConsole")
	procAttachConsole = modKernel32.NewProc("AttachConsole")
	procGetConsoleWnd = modKernel32.NewProc("GetConsoleWindow")
	procGetStdHandle  = modKernel32.NewProc("GetStdHandle")
	procGetConsoleMod = modKernel32.NewProc("GetConsoleMode")
	procSetConsoleTit = modKernel32.NewProc("SetConsoleTitleW")
	procSetConsoleMod = modKernel32.NewProc("SetConsoleMode")
	procSetCtrlHandl  = modKernel32.NewProc("SetConsoleCtrlHandler")
	procShowWindow    = syscall.NewLazyDLL("user32.dll").NewProc("ShowWindow")
)

const hideWindow = 0

func ResolveConsoleMode(runtimeMode string) ConsoleMode {
	if runtimeMode == "product" {
		return ConsoleHidden
	}
	return ConsoleVisible
}

func EnsureConsoleMode(mode ConsoleMode) error {
	if mode == ConsoleHidden {
		hideCurrentConsoleWindow()
		return nil
	}
	if hasConsoleWindow() {
		return enableVirtualTerminalOutput()
	}

	if ok, err := callConsoleProc(procAttachConsole, attachParentProcess); ok {
		if err := attachStandardStreams(); err != nil {
			return err
		}
		return enableVirtualTerminalOutput()
	} else if err != nil && err != syscall.Errno(5) {
		return err
	}

	if ok, err := callConsoleProc(procAllocConsole); !ok {
		return err
	}
	if err := attachStandardStreams(); err != nil {
		return err
	}
	return enableVirtualTerminalOutput()
}

func BuildConsoleTitle(projectRoot string, runtimeMode string, frontendMode string) string {
	projectName := filepath.Base(projectRoot)
	if projectName == "." || projectName == string(filepath.Separator) || projectName == "" {
		projectName = "launcher"
	}
	return fmt.Sprintf("%s launcher [%s/%s]", projectName, runtimeMode, frontendMode)
}

func SetConsoleTitle(title string) error {
	if title == "" {
		return nil
	}
	ptr, err := syscall.UTF16PtrFromString(title)
	if err != nil {
		return err
	}
	result, _, callErr := procSetConsoleTit.Call(uintptr(unsafe.Pointer(ptr)))
	if result != 0 {
		return nil
	}
	if callErr != syscall.Errno(0) {
		return callErr
	}
	return syscall.EINVAL
}

func hasConsoleWindow() bool {
	result, _, _ := procGetConsoleWnd.Call()
	return result != 0
}

func callConsoleProc(proc *syscall.LazyProc, args ...uintptr) (bool, error) {
	result, _, err := proc.Call(args...)
	if result != 0 {
		return true, nil
	}
	if err != syscall.Errno(0) {
		return false, err
	}
	return false, syscall.EINVAL
}

func attachStandardStreams() error {
	stdout, err := os.OpenFile("CONOUT$", os.O_RDWR, 0)
	if err != nil {
		return err
	}
	stderr, err := os.OpenFile("CONOUT$", os.O_RDWR, 0)
	if err != nil {
		return err
	}
	stdin, err := os.OpenFile("CONIN$", os.O_RDWR, 0)
	if err != nil {
		return err
	}

	os.Stdout = stdout
	os.Stderr = stderr
	os.Stdin = stdin
	return nil
}

func enableVirtualTerminalOutput() error {
	if err := enableVirtualTerminalModeForHandle(stdOutputHandle); err != nil {
		return err
	}
	return enableVirtualTerminalModeForHandle(stdErrorHandle)
}

func enableVirtualTerminalModeForHandle(stdHandleID uintptr) error {
	handle, _, handleErr := procGetStdHandle.Call(stdHandleID)
	if handle == 0 || handle == ^uintptr(0) {
		if handleErr != syscall.Errno(0) {
			return handleErr
		}
		return syscall.EINVAL
	}

	var mode uint32
	result, _, modeErr := procGetConsoleMod.Call(handle, uintptr(unsafe.Pointer(&mode)))
	if result == 0 {
		if modeErr != syscall.Errno(0) {
			return modeErr
		}
		return syscall.EINVAL
	}

	nextMode, changed := applyVirtualTerminalMode(mode)
	if !changed {
		return nil
	}

	result, _, setErr := procSetConsoleMod.Call(handle, uintptr(nextMode))
	if result != 0 {
		return nil
	}
	if setErr != syscall.Errno(0) {
		return setErr
	}
	return syscall.EINVAL
}

func applyVirtualTerminalMode(current uint32) (uint32, bool) {
	next := current | enableVirtualTerminalProcessing
	return next, next != current
}

func hasAttachedConsoleHandle(stdHandleID uintptr) bool {
	handle, _, _ := procGetStdHandle.Call(stdHandleID)
	if handle == 0 || handle == ^uintptr(0) {
		return false
	}

	var mode uint32
	result, _, _ := procGetConsoleMod.Call(handle, uintptr(unsafe.Pointer(&mode)))
	return result != 0
}

func hideCurrentConsoleWindow() {
	result, _, _ := procGetConsoleWnd.Call()
	if result == 0 {
		return
	}
	_, _, _ = procShowWindow.Call(result, hideWindow)
}

func InstallConsoleCloseHandler(cancel func(), done <-chan struct{}, timeout time.Duration) (func(), error) {
	if cancel == nil {
		return func() {}, nil
	}
	if timeout <= 0 {
		timeout = 1500 * time.Millisecond
	}

	callback := syscall.NewCallback(func(ctrlType uintptr) uintptr {
		if !isGracefulConsoleShutdownEvent(uint32(ctrlType)) {
			return 0
		}

		cancel()
		waitForConsoleShutdown(done, timeout)
		return 1
	})

	if ok, err := setConsoleCtrlHandler(callback, true); !ok {
		return nil, err
	}

	return func() {
		_, _ = setConsoleCtrlHandler(callback, false)
	}, nil
}

func isGracefulConsoleShutdownEvent(ctrlType uint32) bool {
	switch ctrlType {
	case ctrlCloseEvent, ctrlLogoffEvent, ctrlShutdownEvent:
		return true
	default:
		return false
	}
}

func waitForConsoleShutdown(done <-chan struct{}, timeout time.Duration) {
	if done == nil {
		return
	}
	timer := time.NewTimer(timeout)
	defer timer.Stop()

	select {
	case <-done:
	case <-timer.C:
	}
}

func setConsoleCtrlHandler(handler uintptr, add bool) (bool, error) {
	addFlag := uintptr(0)
	if add {
		addFlag = 1
	}
	result, _, err := procSetCtrlHandl.Call(handler, addFlag)
	if result != 0 {
		return true, nil
	}
	if err != syscall.Errno(0) {
		return false, err
	}
	return false, syscall.EINVAL
}
