package windows

import (
	"fmt"
	"syscall"
	"unsafe"
)

var (
	procCreateJobObjectW         = modKernel32.NewProc("CreateJobObjectW")
	procAssignProcessToJobObject = modKernel32.NewProc("AssignProcessToJobObject")
	procSetInformationJobObject  = modKernel32.NewProc("SetInformationJobObject")
)

const (
	jobObjectInfoClassExtendedLimitInformation = 9
	jobObjectLimitKillOnJobClose               = 0x00002000
	jobObjectLimitSilentBreakawayOK            = 0x00001000
	processSetQuota                            = 0x0100
	processTerminate                           = 0x0001
)

type ioCounters struct {
	ReadOperationCount  uint64
	WriteOperationCount uint64
	OtherOperationCount uint64
	ReadTransferCount   uint64
	WriteTransferCount  uint64
	OtherTransferCount  uint64
}

type JobObject struct {
	handle syscall.Handle
}

func CreateOwnedProcessJobObject() (*JobObject, error) {
	handle, _, callErr := procCreateJobObjectW.Call(0, 0)
	if handle == 0 {
		if callErr != syscall.Errno(0) {
			return nil, callErr
		}
		return nil, syscall.EINVAL
	}

	job := &JobObject{handle: syscall.Handle(handle)}
	if err := job.applyOwnedProcessLimits(); err != nil {
		_ = job.Close()
		return nil, err
	}
	return job, nil
}

func (job *JobObject) Attach(pid int) error {
	if job == nil || job.handle == 0 {
		return fmt.Errorf("job object is not initialized")
	}
	if pid <= 0 {
		return fmt.Errorf("invalid pid: %d", pid)
	}

	processHandle, _, callErr := procOpenProcess.Call(ownedProcessAccessRights(), 0, uintptr(uint32(pid)))
	if processHandle == 0 {
		if callErr != syscall.Errno(0) {
			return callErr
		}
		return syscall.EINVAL
	}
	defer procCloseHandle.Call(processHandle)

	result, _, callErr := procAssignProcessToJobObject.Call(uintptr(job.handle), processHandle)
	if result == 0 {
		if callErr != syscall.Errno(0) {
			return callErr
		}
		return syscall.EINVAL
	}
	return nil
}

func ownedProcessAccessRights() uintptr {
	return processSetQuota | processQueryLimitedInfo | processTerminate
}

func (job *JobObject) Close() error {
	if job == nil || job.handle == 0 {
		return nil
	}
	procCloseHandle.Call(uintptr(job.handle))
	job.handle = 0
	return nil
}

func (job *JobObject) applyOwnedProcessLimits() error {
	info := buildOwnedProcessJobObjectInfo()
	result, _, callErr := procSetInformationJobObject.Call(
		uintptr(job.handle),
		uintptr(jobObjectInfoClassExtendedLimitInformation),
		uintptr(unsafe.Pointer(&info)),
		unsafe.Sizeof(info),
	)
	if result == 0 {
		if callErr != syscall.Errno(0) {
			return callErr
		}
		return syscall.EINVAL
	}
	return nil
}

func buildOwnedProcessJobObjectInfo() jobObjectExtendedLimitInformation {
	return jobObjectExtendedLimitInformation{
		BasicLimitInformation: jobObjectBasicLimitInformation{
			LimitFlags: jobObjectLimitKillOnJobClose | jobObjectLimitSilentBreakawayOK,
		},
	}
}
