//go:build windows

package hooks

import (
	"os"
	"os/exec"
	"sync"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

func startNativeProcess(cmd *exec.Cmd) (func(), error) {
	job, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return nil, err
	}
	limits := windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION{}
	limits.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	if _, err = windows.SetInformationJobObject(job, windows.JobObjectExtendedLimitInformation, uintptr(unsafe.Pointer(&limits)), uint32(unsafe.Sizeof(limits))); err != nil {
		windows.CloseHandle(job)
		return nil, err
	}
	var mu sync.Mutex
	stop := func() {
		mu.Lock()
		defer mu.Unlock()
		if job != 0 {
			_ = windows.TerminateJobObject(job, 1)
			windows.CloseHandle(job)
			job = 0
		}
	}
	cmd.Cancel = func() error {
		mu.Lock()
		defer mu.Unlock()
		if job == 0 {
			return os.ErrProcessDone
		}
		return windows.TerminateJobObject(job, 1)
	}
	// Assign the suspended host before it can spawn a child outside our Job.
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_SUSPENDED | windows.CREATE_NO_WINDOW}
	// Cancellation must wait until the process belongs to the Job; terminating
	// an empty Job before assignment would leave the new host running.
	mu.Lock()
	if err = cmd.Start(); err != nil {
		mu.Unlock()
		stop()
		return nil, err
	}
	process, err := windows.OpenProcess(windows.PROCESS_SET_QUOTA|windows.PROCESS_TERMINATE, false, uint32(cmd.Process.Pid))
	if err == nil {
		err = windows.AssignProcessToJobObject(job, process)
		windows.CloseHandle(process)
	}
	if err == nil {
		err = resumeNativeProcess(uint32(cmd.Process.Pid))
	}
	mu.Unlock()
	if err != nil {
		_ = cmd.Process.Kill()
		stop()
		_ = cmd.Wait()
		return nil, err
	}
	return stop, nil
}

func resumeNativeProcess(pid uint32) error {
	snapshot, err := windows.CreateToolhelp32Snapshot(windows.TH32CS_SNAPTHREAD, 0)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(snapshot)
	entry := windows.ThreadEntry32{Size: uint32(unsafe.Sizeof(windows.ThreadEntry32{}))}
	for err = windows.Thread32First(snapshot, &entry); err == nil; err = windows.Thread32Next(snapshot, &entry) {
		if entry.OwnerProcessID != pid {
			continue
		}
		thread, err := windows.OpenThread(windows.THREAD_SUSPEND_RESUME, false, entry.ThreadID)
		if err != nil {
			return err
		}
		_, err = windows.ResumeThread(thread)
		windows.CloseHandle(thread)
		return err
	}
	return os.ErrProcessDone
}
