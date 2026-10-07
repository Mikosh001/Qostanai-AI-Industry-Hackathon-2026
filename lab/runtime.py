"""Run lab scripts in base Python with the selected venv's dependencies.

Windows venv redirectors own kill-on-exit Jobs. Long-lived servers must never
be launched through a redirector, even when their launcher is independent.
"""
import os, runpy, sys, site
from pathlib import Path


def main():
    python, script, *arguments = sys.argv[1:]
    site = Path(python).resolve().parent.parent / 'Lib' / 'site-packages'
    if not site.is_dir():
        raise RuntimeError('Selected Python environment has no site-packages')
    project = Path(__file__).resolve().parent.parent
    paths = [str(site), str(project)]
    # .pth files also configure pywin32's DLL search path.
    __import__('site').addsitedir(str(site))
    sys.path[:0] = paths
    os.environ['PYTHONPATH'] = os.pathsep.join(paths + [os.environ.get('PYTHONPATH', '')])
    os.environ['SERGEK_LAB_PYTHON'] = python
    if script == '--module':
        module, *arguments = arguments
        sys.argv = [module, *arguments]
        runpy.run_module(module, run_name='__main__')
        return
    sys.path.insert(0, str(Path(script).resolve().parent))
    sys.argv = [script, *arguments]
    runpy.run_path(script, run_name='__main__')


if __name__ == '__main__':
    main()
