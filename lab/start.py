"""Start/stop the isolated lab; all background children are hidden, loopback-only."""

import sys, os, json, subprocess, time, secrets, hashlib
from pathlib import Path
import psutil
from setup import LAB, ROOT, FLAGS, prepare, run

sys.path.insert(0, str(ROOT))


def owned_process(name, pid):
    """A reused PID must never count as a lab helper or be terminated."""
    try:
        process = psutil.Process(pid)
        exe = Path(process.exe()).resolve()
        args = process.cmdline()
        if name == "db":
            return process if (exe.is_relative_to(LAB) and exe.name.lower() == "mariadbd.exe"
                and "--defaults-file=" + str(LAB / "db" / "my.ini") in args) else None
        if process.environ().get("SERGEK_LAB") != str(LAB):
            return None
        if name == "php":
            valid = exe == (LAB / "php" / "php.exe").resolve() and "127.0.0.1:8088" in args
        elif name == "tls":
            valid = exe in {Path(sys.executable).resolve(), Path(sys._base_executable).resolve()} and str(ROOT / "lab" / "proxy.py") in args
        elif name == "hub":
            valid = exe in {Path(sys.executable).resolve(), Path(sys._base_executable).resolve()} and "backend.run" in args and "9443" in args
        else:
            valid = False
        return process if valid else None
    except psutil.Error:
        return None


def revision(name):
    files = sorted((ROOT / "backend").glob("*.py")) if name == "hub" else [ROOT / "lab" / "proxy.py"] if name == "tls" else []
    files += [ROOT / 'lab' / 'runtime.py', ROOT / 'lab' / 'start.py']
    return hashlib.sha256(b"".join(file.read_bytes() for file in files)).hexdigest()


def stop():
    if not (LAB / "pids.json").exists():
        return
    pids = json.loads((LAB / "pids.json").read_text())
    for name, pid in pids.items():
        try:
            process = owned_process(name, pid)
            if process is None:
                print("Skipped stale or unrelated PID", pid)
                continue
            process.terminate()
            process.wait(timeout=8)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            print("Process did not stop", pid)
    (LAB / "pids.json").unlink(missing_ok=True)


def start():
    from independent import process_in_job
    prepare()
    meta = json.loads((LAB / "lab.json").read_text())
    private_file = LAB / "credentials.json"
    credentials = json.loads(private_file.read_text(encoding="utf-8"))
    credentials.setdefault("moodle_teacher", "sergek.teacher")
    credentials.setdefault("moodle_teacher_password", "Demo!" + secrets.token_urlsafe(18) + "9aA")
    private_file.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    # Base Python avoids the venv redirector's private Job. Its dependencies
    # travel explicitly to children; no machine-wide PATH or Python changes.
    env = {**os.environ, "SERGEK_LAB": str(LAB), "PYTHONPATH": os.pathsep.join(sys.path)}
    run(
        [
            meta["php"],
            "-d",
            "display_errors=stderr",
            "-d",
            "log_errors=0",
            ROOT / "lab" / "seed.php",
        ],
        env=env,
    )
    pids = json.loads((LAB / "pids.json").read_text())
    service_runtime = [sys._base_executable, str(ROOT/'lab/runtime.py'), os.environ.get('SERGEK_LAB_PYTHON', sys.executable)]
    commands = {
        "php": [meta["php"], "-S", "127.0.0.1:8088", "-t", meta["moodle"]],
        "tls": [*service_runtime, str(ROOT / "lab" / "proxy.py")],
        "hub": [
            *service_runtime,
            "--module",
            "backend.run",
            "--host",
            "127.0.0.1",
            "--port",
            "9443",
            "--cert",
            str(LAB / "localhost.crt"),
            "--key",
            str(LAB / "localhost.key"),
        ],
    }
    for name, args in commands.items():
        previous = owned_process(name, pids[name]) if pids.get(name) else None
        current_revision = revision(name)
        if previous is not None:
            if previous.environ().get("SERGEK_LAB_REVISION") == current_revision and previous.environ().get('SERGEK_LAB_LIFETIME') == 'base-runtime-v2' and not process_in_job(previous.pid):
                continue
            previous.terminate()
            previous.wait(timeout=8)
        log = (LAB / (name + ".log")).open("ab")
        childenv = {
            **env,
            "SERGEK_DATA": str(LAB / "hub"),
            "SERGEK_DESKTOP_KEY": "isolated-lab-bootstrap",
            "SERGEK_CA_FILE": str(LAB / "localhost.crt"),
            "SERGEK_LAB_REVISION": current_revision,
            "SERGEK_LAB_LIFETIME": "base-runtime-v2",
        }
        process = subprocess.Popen(
            args, env=childenv, cwd=ROOT, stdout=log, stderr=log, creationflags=FLAGS
        )
        pids[name] = process.pid
    (LAB / "pids.json").write_text(json.dumps(pids))
    time.sleep(3)
    import httpx, ssl

    creds = json.loads((LAB / "credentials.json").read_text())
    with httpx.Client(
        verify=ssl.create_default_context(cafile=str(LAB / "localhost.crt"))
    ) as client:
        for attempt in range(30):
            try:
                if client.get(meta["hub"] + "/api/health").is_success and client.get(meta["url"] + "login/index.php").is_success:
                    break
            except httpx.TransportError:
                time.sleep(1)
        if client.get(meta["hub"] + "/api/health").json()["setup_required"]:
            client.post(
                meta["hub"] + "/api/setup",
                headers={"x-sergek-desktop": "isolated-lab-bootstrap"},
                json={"password": creds["teacherpass"]},
            ).raise_for_status()
        client.post(
            meta["hub"] + "/api/auth/login", json={"password": creds["teacherpass"]}
        ).raise_for_status()
        client.put(
            meta["hub"] + "/api/integration/moodle", json={"key": creds["sharedkey"]}
        ).raise_for_status()
        # This is test fixture preparation in a new isolated DB, never a university profile.
        from backend.store import Store

        store = Store(LAB / "hub" / "sergek.db")
        store.set_setting("hub_receive_key", creds["hubkey"])
        store.db.close()
        client.post(meta["hub"] + "/api/auth/logout")
    print(
        "Moodle lab: https://localhost/; hub: https://localhost:9443/; credentials:",
        LAB / "credentials.json",
    )


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop()
    else:
        start()
