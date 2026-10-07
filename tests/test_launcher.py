"""Real Windows lifetime test, only two inert owned Python children are touched."""
import ctypes, importlib.util, json, os, subprocess, sys, time
from pathlib import Path
from ctypes import wintypes as w
import psutil
import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows process lifetime")
def test_detached_exam_survives_supervisor_job_close(tmp_path):
    path=Path(__file__).resolve().parents[1]/'lab/independent.py'
    spec=importlib.util.spec_from_file_location('independent_launch',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    script=tmp_path/'inert_target.py'
    script.write_text('''import ctypes,json,os,sys,time
from ctypes import wintypes as w
from pathlib import Path
time.sleep(.3)
k=ctypes.WinDLL("kernel32");k.GetCurrentProcess.restype=w.HANDLE;k.IsProcessInJob.argtypes=[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)]
v=w.BOOL();k.IsProcessInJob(k.GetCurrentProcess(),None,ctypes.byref(v))
Path(sys.argv[1]).write_text(json.dumps({"pid":os.getpid(),"in_job":bool(v.value)}))
time.sleep(30)
''')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    job=kernel.CreateJobObjectW(None,None);assert job
    limits=ctypes.create_string_buffer(144)
    ctypes.c_uint32.from_buffer(limits,16).value=0x2000
    assert kernel.SetInformationJobObject(job,9,limits,len(limits))
    normal=None;independent=None
    try:
        normal=subprocess.Popen([sys._base_executable,str(script),str(tmp_path/'normal.json')],creationflags=subprocess.CREATE_NO_WINDOW)
        assert kernel.AssignProcessToJobObject(job,w.HANDLE(int(normal._handle)))
        pid=module.start_independent([sys._base_executable,script,tmp_path/'detached.json'],tmp_path,hidden=True)
        independent=psutil.Process(pid)
        deadline=time.monotonic()+8
        while not all((tmp_path/name).exists() for name in ['normal.json','detached.json']) and time.monotonic()<deadline:time.sleep(.1)
        assert json.loads((tmp_path/'normal.json').read_text())['in_job']
        assert not json.loads((tmp_path/'detached.json').read_text())['in_job']
        kernel.CloseHandle(job);job=None
        normal.wait(timeout=5)
        time.sleep(.5)
        assert independent.is_running()
    finally:
        if job:kernel.CloseHandle(job)
        if normal and normal.poll() is None:normal.terminate();normal.wait(timeout=5)
        if independent and independent.is_running():
            assert Path(independent.exe()).resolve()==Path(sys._base_executable).resolve()
            assert str(script) in independent.cmdline()
            independent.terminate();independent.wait(timeout=5)
