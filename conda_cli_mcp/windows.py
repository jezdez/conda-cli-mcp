from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_RESUME_FAILED = 0xFFFFFFFF

CREATE_SUSPENDED = 0x00000004

_load_library: Any = getattr(ctypes, "WinDLL")
_get_last_error: Any = getattr(ctypes, "get_last_error")
_kernel32: Any = _load_library("kernel32", use_last_error=True)

_create_job_object = _kernel32.CreateJobObjectW
_create_job_object.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
_create_job_object.restype = wintypes.HANDLE

_open_process = _kernel32.OpenProcess
_open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_open_process.restype = wintypes.HANDLE

_assign_process = _kernel32.AssignProcessToJobObject
_assign_process.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
_assign_process.restype = wintypes.BOOL

_set_job_information = _kernel32.SetInformationJobObject
_set_job_information.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
)
_set_job_information.restype = wintypes.BOOL

_terminate_job = _kernel32.TerminateJobObject
_terminate_job.argtypes = (wintypes.HANDLE, wintypes.UINT)
_terminate_job.restype = wintypes.BOOL

_create_snapshot = _kernel32.CreateToolhelp32Snapshot
_create_snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_create_snapshot.restype = wintypes.HANDLE

_thread_first = _kernel32.Thread32First
_thread_first.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
_thread_first.restype = wintypes.BOOL

_thread_next = _kernel32.Thread32Next
_thread_next.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
_thread_next.restype = wintypes.BOOL

_open_thread = _kernel32.OpenThread
_open_thread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_open_thread.restype = wintypes.HANDLE

_resume_thread = _kernel32.ResumeThread
_resume_thread.argtypes = (wintypes.HANDLE,)
_resume_thread.restype = wintypes.DWORD

_close_handle = _kernel32.CloseHandle
_close_handle.argtypes = (wintypes.HANDLE,)
_close_handle.restype = wintypes.BOOL


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    )


class _IoCounters(ctypes.Structure):
    _fields_ = (
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    )


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = (
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


class _ThreadEntry(ctypes.Structure):
    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    )


def _error(operation: str) -> OSError:
    return OSError(_get_last_error(), f"{operation} failed")


class WindowsJob:
    """Own a Windows job object that tracks one subprocess tree."""

    def __init__(self) -> None:
        self._handle: int | None = _create_job_object(None, None)
        if self._handle is None:
            raise _error("CreateJobObjectW")

        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _set_job_information(
            self._handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = _error("SetInformationJobObject")
            self.close()
            raise error

    def assign_and_resume(self, pid: int) -> None:
        """Assign a suspended process to the job, then resume its main thread."""
        process = _open_process(
            _PROCESS_TERMINATE | _PROCESS_SET_QUOTA,
            False,
            pid,
        )
        if process is None:
            raise _error("OpenProcess")
        try:
            if not _assign_process(self._handle, process):
                raise _error("AssignProcessToJobObject")
        finally:
            _close_handle(process)

        thread = self._open_process_thread(pid)
        try:
            if _resume_thread(thread) == _RESUME_FAILED:
                raise _error("ResumeThread")
        finally:
            _close_handle(thread)

    @staticmethod
    def _open_process_thread(pid: int) -> int:
        snapshot = _create_snapshot(_TH32CS_SNAPTHREAD, 0)
        if snapshot == _INVALID_HANDLE_VALUE:
            raise _error("CreateToolhelp32Snapshot")
        try:
            entry = _ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            available = _thread_first(snapshot, ctypes.byref(entry))
            while available:
                if entry.th32OwnerProcessID == pid:
                    thread = _open_thread(
                        _THREAD_SUSPEND_RESUME,
                        False,
                        entry.th32ThreadID,
                    )
                    if thread is None:
                        raise _error("OpenThread")
                    return thread
                available = _thread_next(snapshot, ctypes.byref(entry))
        finally:
            _close_handle(snapshot)
        raise OSError(f"no thread found for suspended process {pid}")

    def terminate(self) -> None:
        """Terminate every process still assigned to the job."""
        if self._handle is not None and not _terminate_job(self._handle, 1):
            raise _error("TerminateJobObject")

    def close(self) -> None:
        """Release the job handle and terminate any remaining processes."""
        if self._handle is not None:
            _close_handle(self._handle)
            self._handle = None
