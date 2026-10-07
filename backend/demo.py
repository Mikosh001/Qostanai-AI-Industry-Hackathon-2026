"""Explicit local demo bootstrap. Never changes a university or existing user database."""
import json
from pathlib import Path
from .config import Profile, HubConfig
from .security import hash_password


def bootstrap_demo(store, config_file):
    source = Path(config_file).resolve()
    config = json.loads(source.read_text(encoding="utf-8"))
    target = Path(config["data"]).resolve()
    if target.parent != source.parent or target.name != "demo-agent":
        raise ValueError("Demo requires a dedicated demo-agent directory")
    if Path(store.db.execute("PRAGMA database_list").fetchone()[2]).resolve().parent != target:
        raise ValueError("Refusing to reconfigure a non-demo database")
    p = Profile.model_validate(config["profile"])
    if p.allowed_hosts != ["localhost"] or p.moodle_url != "https://localhost/" or p.platonus_url != "https://localhost/":
        raise ValueError("Demo must use only the isolated localhost Moodle")
    pin = p.tls_pins.get("localhost", "")
    if len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin):
        raise ValueError("Local certificate fingerprint required")
    hub = HubConfig.model_validate(config["hub"])
    if hub.url != "https://localhost:9443" or not hub.enabled or len(hub.pairing_key) < 32:
        raise ValueError("Local authenticated hub required")
    if p.exam_mode != "strict" or not all(getattr(p.policy, x) for x in (
        "camera_required", "microphone_required", "screen_recording", "close_applications",
        "remote_block", "usb_block", "keyboard_block", "single_monitor"
    )):
        raise ValueError("Demo bootstrap must retain full protection")
    if len(config["moodle_key"]) < 32 or len(config["teacher_password"]) < 12:
        raise ValueError("Invalid demo credentials")
    if not store.setting("password"):
        store.set_setting("password", hash_password(config["teacher_password"]))
    store.set_setting("profile", p.model_dump())
    store.set_setting("moodle_key", config["moodle_key"])
    store.set_setting("hub", hub.model_dump())
    store.audit("local_demo_bootstrap", {"moodle_url": p.moodle_url, "protection": "strict"})
