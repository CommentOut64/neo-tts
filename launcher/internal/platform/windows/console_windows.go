package windows

import (
	"os"
	"syscall"
)

type ConsoleMode string

const (
	ConsoleVisible ConsoleMode = "visible"
	ConsoleHidden  ConsoleMode = "hidden"
)

const attachParentProcess = ^uintptr(0)

var (
	procAllocConsole  = modKernel32.NewProc("AllocConsole")
	procAttachConsole = modKernel32.NewProc("AttachConsole")
	procGetConsoleWnd = modKernel32.NewProc("GetConsoleWindow")
)

func ResolveConsoleMode(runtimeMode string) ConsoleMode {
	if runtimeMode == "product" {
		return ConsoleHidden
	}
	return ConsoleVisible
}

func EnsureConsoleMode(mode ConsoleMode) error {
	if mode != ConsoleVisible || hasConsoleWindow() {
		return nil
	}

	if ok, err := callConsoleProc(procAttachConsole, attachParentProcess); ok {
		return attachStandardStreams()
	} else if err != nil && err != syscall.Errno(5) {
		return err
	}

	if ok, err := callConsoleProc(procAllocConsole); !ok {
		return err
	}
	return attachStandardStreams()
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
