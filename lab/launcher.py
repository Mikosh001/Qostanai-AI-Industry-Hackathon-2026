"""Independent local-lab launcher; services and exam outlive the calling editor."""
import argparse, ctypes, json, os, subprocess, sys, time, uuid
from pathlib import Path
from ctypes import wintypes as w

ROOT = Path(__file__).resolve().parent.parent


class ShellInfo(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("mask", w.ULONG), ("window", w.HWND),
        ("verb", w.LPCWSTR), ("file", w.LPCWSTR), ("parameters", w.LPCWSTR),
        ("directory", w.LPCWSTR), ("show", ctypes.c_int), ("instance", w.HANDLE),
        ("idlist", ctypes.c_void_p), ("class_name", w.LPCWSTR), ("class_key", w.HKEY),
        ("hotkey", w.DWORD), ("icon", w.HANDLE), ("process", w.HANDLE)]


def worker(args):
    from independent import in_job
    status = Path(args.status)
    status.parent.mkdir(parents=True, exist_ok=True)
    log = status.with_suffix(".log")
    result = {}
    try:
        if in_job(): raise RuntimeError("Exam launcher is still attached to a supervisor Job")
        config_result=status.with_suffix('.config.json')
        with log.open("w", encoding="utf-8") as output:
            subprocess.run([sys._base_executable, str(ROOT / "lab/runtime.py"), args.python, str(ROOT / "lab/demo.py"), "--configure", "--config-result="+str(config_result)],
                cwd=ROOT, stdout=output, stderr=output, check=True,
                creationflags=subprocess.CREATE_NO_WINDOW)
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellInfo)]
        info = ShellInfo(); info.size = ctypes.sizeof(info); info.mask = 0x40 | 0x100
        info.verb = "open"; info.file = args.executable; info.directory = str(ROOT); info.show = 1
        config=json.loads(config_result.read_text(encoding='utf-8'))['config']
        info.parameters=subprocess.list2cmdline(["--demo-config="+config])
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
        kernel.GetProcessId.argtypes = [w.HANDLE]; kernel.GetProcessId.restype = w.DWORD
        kernel.CloseHandle.argtypes = [w.HANDLE]
        attached = w.BOOL()
        try:
            if not info.process or not kernel.IsProcessInJob(info.process, None, ctypes.byref(attached)):
                raise RuntimeError("Cannot verify independent exam process")
            # Electron/Windows may create its own Job; the supervisor has no Job.
            result = {"ok": True, "pid": kernel.GetProcessId(info.process),
                      "independent_supervisor": True, "application_job": bool(attached.value)}
        finally:
            if info.process: kernel.CloseHandle(info.process)
    except Exception as error:
        result = {"ok": False, "error": str(error), "log": str(log)}
    temporary=status.with_suffix('.tmp')
    temporary.write_text(json.dumps(result), encoding="utf-8")
    temporary.replace(status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--status", default="")
    args = parser.parse_args()
    if args.worker: worker(args); return
    from independent import start_independent
    # A packaged editor may virtualize AppData; the detached worker has no package
    # identity. Keep their rendezvous in the actual project, visible to both.
    destination = ROOT / "runtime" / "launches"
    destination.mkdir(parents=True, exist_ok=True)
    status = destination / (uuid.uuid4().hex + ".json")
    # The venv redirector creates its own kill-on-close Job. Use the base runtime
    # for the independent supervisor, and the venv only for dependency-rich setup.
    start_independent([sys._base_executable, __file__, "--worker", "--python", args.python,
        "--executable", str(Path(args.executable).resolve(strict=True)), "--status", status], ROOT, hidden=True)
    print("Starting independent Moodle and Sergек...", flush=True)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if status.exists():
            result = json.loads(status.read_text(encoding="utf-8"))
            if not result["ok"]: raise RuntimeError(result["error"] + "; log: " + result["log"])
            print("Sergек started independently. PID:", result["pid"])
            return
        time.sleep(.2)
    raise TimeoutError("Launcher did not finish; inspect " + str(status.with_suffix('.log')))


if __name__ == "__main__": main()
