package windows

import (
	"encoding/binary"
	"fmt"
	"syscall"
	"unsafe"
)

var (
	modIPHlpAPI             = syscall.NewLazyDLL("iphlpapi.dll")
	procGetExtendedTCPTable = modIPHlpAPI.NewProc("GetExtendedTcpTable")
	procOpenProcess         = modKernel32.NewProc("OpenProcess")
	procGetExitCodeProcess  = modKernel32.NewProc("GetExitCodeProcess")
)

const (
	afINET                   = 2
	tcpTableOwnerPIDListener = 3
	processQueryLimitedInfo  = 0x1000
	stillActive              = 259
)

type tcpRowOwnerPID struct {
	State      uint32
	LocalAddr  uint32
	LocalPort  uint32
	RemoteAddr uint32
	RemotePort uint32
	OwningPID  uint32
}

func IsProcessRunning(pid int) bool {
	if pid <= 0 {
		return false
	}

	handle, _, _ := procOpenProcess.Call(processQueryLimitedInfo, 0, uintptr(uint32(pid)))
	if handle == 0 {
		return false
	}
	defer procCloseHandle.Call(handle)

	var exitCode uint32
	result, _, _ := procGetExitCodeProcess.Call(handle, uintptr(unsafe.Pointer(&exitCode)))
	return result != 0 && exitCode == stillActive
}

func FindListeningPIDByPort(port int) (int, error) {
	rows, err := readListeningTCPRows()
	if err != nil {
		return 0, err
	}
	return findListeningPIDByPortFromRows(port, rows)
}

func readListeningTCPRows() ([]tcpRowOwnerPID, error) {
	var size uint32
	result, _, callErr := procGetExtendedTCPTable.Call(
		0,
		uintptr(unsafe.Pointer(&size)),
		0,
		uintptr(afINET),
		uintptr(tcpTableOwnerPIDListener),
		0,
	)
	if result != 0 && syscall.Errno(result) != syscall.ERROR_INSUFFICIENT_BUFFER {
		if callErr != syscall.Errno(0) {
			return nil, callErr
		}
		return nil, fmt.Errorf("GetExtendedTcpTable sizing failed: %d", result)
	}
	if size == 0 {
		return nil, nil
	}

	buffer := make([]byte, size)
	result, _, callErr = procGetExtendedTCPTable.Call(
		uintptr(unsafe.Pointer(&buffer[0])),
		uintptr(unsafe.Pointer(&size)),
		0,
		uintptr(afINET),
		uintptr(tcpTableOwnerPIDListener),
		0,
	)
	if result != 0 {
		if callErr != syscall.Errno(0) {
			return nil, callErr
		}
		return nil, fmt.Errorf("GetExtendedTcpTable failed: %d", result)
	}

	entryCount := *(*uint32)(unsafe.Pointer(&buffer[0]))
	if entryCount == 0 {
		return nil, nil
	}

	rows := make([]tcpRowOwnerPID, 0, entryCount)
	offset := uintptr(unsafe.Sizeof(entryCount))
	rowSize := unsafe.Sizeof(tcpRowOwnerPID{})
	for index := uint32(0); index < entryCount; index++ {
		row := *(*tcpRowOwnerPID)(unsafe.Pointer(&buffer[offset]))
		rows = append(rows, row)
		offset += rowSize
	}
	return rows, nil
}

func findListeningPIDByPortFromRows(port int, rows []tcpRowOwnerPID) (int, error) {
	if port <= 0 {
		return 0, nil
	}

	for _, row := range rows {
		if decodeTCPPort(row.LocalPort) == port {
			return int(row.OwningPID), nil
		}
	}
	return 0, nil
}

func decodeTCPPort(raw uint32) int {
	bytes := *(*[4]byte)(unsafe.Pointer(&raw))
	return int(binary.BigEndian.Uint16(bytes[:2]))
}
