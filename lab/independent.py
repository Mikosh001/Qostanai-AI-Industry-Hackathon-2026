"""Start the local desktop lab with Explorer's independent process lifetime.

A development host can own a kill-on-close Windows Job. Closing that host during
an exam must not also terminate the exam or its local Moodle server.
"""
import ctypes
import os
import subprocess
from pathlib import Path
from ctypes import wintypes as w


class StartupInfo(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
        ("title", w.LPWSTR), ("x", w.DWORD), ("y", w.DWORD),
        ("width", w.DWORD), ("height", w.DWORD), ("xchars", w.DWORD),
        ("ychars", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
        ("show", w.WORD), ("reserved_size", w.WORD), ("reserved_data", ctypes.c_void_p),
        ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", ctypes.c_void_p)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


def in_job():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    value = w.BOOL()
    if not kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    return bool(value.value)


def process_in_job(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return True  # Do not reuse a lifetime we cannot verify.
    try:
        value = w.BOOL()
        if not kernel.IsProcessInJob(handle, None, ctypes.byref(value)):
            return True
        return bool(value.value)
    finally:
        kernel.CloseHandle(handle)


def start_independent(args, cwd, hidden=False):
    import psutil
    if os.name != "nt":
        raise OSError("Windows required")
    exe = Path(args[0]).resolve(strict=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    kernel.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(StartupInfoEx), ctypes.POINTER(ProcessInfo)]
    own_session = w.DWORD()
    if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(own_session)):
        raise ctypes.WinError(ctypes.get_last_error())
    expected = Path(os.environ["WINDIR"]) / "explorer.exe"
    parent = None
    for process in psutil.process_iter(["pid", "name"]):
        if (process.info["name"] or "").lower() != "explorer.exe":
            continue
        session = w.DWORD()
        if not kernel.ProcessIdToSessionId(process.pid, ctypes.byref(session)) or session.value != own_session.value:
            continue
        handle = kernel.OpenProcess(0x80 | 0x1000, False, process.pid)
        if not handle:
            continue
        name = ctypes.create_unicode_buffer(32768); count = w.DWORD(len(name))
        if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(count)) and Path(name.value).resolve() == expected.resolve():
            parent = handle
            break
        kernel.CloseHandle(handle)
    if not parent:
        raise OSError("Windows Explorer is unavailable; cannot safely detach the exam launcher")
    initialized = False
    try:
        size = ctypes.c_size_t()
        kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        if not kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        initialized = True
        parent_value = w.HANDLE(parent)
        if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x20000, ctypes.byref(parent_value), ctypes.sizeof(parent_value), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        info = StartupInfoEx(); info.startup.cb = ctypes.sizeof(info)
        info.startup.flags = 1; info.startup.show = 0 if hidden else 1
        info.attributes = ctypes.cast(attributes, ctypes.c_void_p)
        result = ProcessInfo()
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(exe), *map(str,args[1:])]))
        flags = 0x80000 | 0x200  # extended startup info, independent process group
        if hidden: flags |= 0x8000000
        if not kernel.CreateProcessW(str(exe), command, None, None, False, flags, None,
                                     str(Path(cwd).resolve()), ctypes.byref(info), ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(result.thread); kernel.CloseHandle(result.process)
        return result.pid
    finally:
        if initialized: kernel.DeleteProcThreadAttributeList(attributes)
        kernel.CloseHandle(parent)
