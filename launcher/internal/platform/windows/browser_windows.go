package windows

import (
	"fmt"
	"os/exec"
	"syscall"
	"unsafe"
)

var (
	shellExecuteURL      = openBrowserWithShellExecute
	startBrowserFallback = openBrowserWithStartProcess
)

func OpenBrowser(url string) error {
	if err := shellExecuteURL(url); err == nil {
		return nil
	}
	return startBrowserFallback(url)
}

func openBrowserWithStartProcess(url string) error {
	invocation := buildOpenBrowserInvocation(url)
	command := exec.Command(invocation.Executable, invocation.Args...)
	ConfigureCommand(command, WindowHidden)
	return command.Start()
}

func openBrowserWithShellExecute(url string) error {
	shell32 := syscall.NewLazyDLL("shell32.dll")
	procShellExecute := shell32.NewProc("ShellExecuteW")

	verb, err := syscall.UTF16PtrFromString("open")
	if err != nil {
		return err
	}
	target, err := syscall.UTF16PtrFromString(url)
	if err != nil {
		return err
	}

	result, _, callErr := procShellExecute.Call(
		0,
		uintptr(unsafe.Pointer(verb)),
		uintptr(unsafe.Pointer(target)),
		0,
		0,
		1,
	)
	if result <= 32 {
		if callErr != syscall.Errno(0) {
			return callErr
		}
		return fmt.Errorf("ShellExecuteW failed with code %d", result)
	}
	return nil
}

func buildOpenBrowserInvocation(url string) CommandInvocation {
	return CommandInvocation{
		Executable: "cmd",
		Args: []string{
			"/c",
			"start",
			"",
			url,
		},
	}
}
