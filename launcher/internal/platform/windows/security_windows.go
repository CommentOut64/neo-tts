package windows

import (
	"syscall"
	"unsafe"
)

var (
	modAdvapi32                  = syscall.NewLazyDLL("advapi32.dll")
	procAllocateAndInitializeSid = modAdvapi32.NewProc("AllocateAndInitializeSid")
	procCheckTokenMembership     = modAdvapi32.NewProc("CheckTokenMembership")
	procFreeSid                  = modAdvapi32.NewProc("FreeSid")
	currentProcessElevatedFn     = currentProcessIsElevatedNative
)

const (
	securityBuiltinDomainRID = 0x00000020
	domainAliasRIDAdmins     = 0x00000220
)

type sidIdentifierAuthority struct {
	Value [6]byte
}

func IsCurrentProcessElevated() (bool, error) {
	return currentProcessElevatedFn()
}

func currentProcessIsElevatedNative() (bool, error) {
	ntAuthority := sidIdentifierAuthority{Value: [6]byte{0, 0, 0, 0, 0, 5}}

	var administratorsGroup uintptr
	result, _, callErr := procAllocateAndInitializeSid.Call(
		uintptr(unsafe.Pointer(&ntAuthority)),
		2,
		uintptr(securityBuiltinDomainRID),
		uintptr(domainAliasRIDAdmins),
		0,
		0,
		0,
		0,
		0,
		0,
		uintptr(unsafe.Pointer(&administratorsGroup)),
	)
	if result == 0 {
		if callErr != syscall.Errno(0) {
			return false, callErr
		}
		return false, syscall.EINVAL
	}
	defer procFreeSid.Call(administratorsGroup)

	var isMember int32
	result, _, callErr = procCheckTokenMembership.Call(
		0,
		administratorsGroup,
		uintptr(unsafe.Pointer(&isMember)),
	)
	if result == 0 {
		if callErr != syscall.Errno(0) {
			return false, callErr
		}
		return false, syscall.EINVAL
	}

	return isMember != 0, nil
}
