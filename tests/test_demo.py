import json
import pytest
from backend.config import Profile
from backend.demo import bootstrap_demo
from backend.store import Store
from backend.security import verify_password


def config(tmp_path):
    value = {
        "data": str(tmp_path / "demo-agent"),
        "profile": Profile(tls_pins={"localhost": "a" * 64}).model_dump(),
        "hub": {"enabled": True, "url": "https://localhost:9443", "pairing_key": "b" * 32},
        "moodle_key": "c" * 32,
        "teacher_password": "LocalDemoPassword123!",
    }
    path = tmp_path / "demo-config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


def test_bootstrap_retains_protection_and_existing_password(tmp_path):
    path, value = config(tmp_path)
    store = Store(tmp_path / "demo-agent" / "sergek.db")
    bootstrap_demo(store, path)
    p = store.setting("profile")
    assert p["moodle_url"] == "https://localhost/" and p["exam_mode"] == "strict"
    assert p["policy"]["camera_required"] and p["policy"]["microphone_required"]
    assert p["policy"]["usb_block"] and p["policy"]["close_applications"]
    old = store.setting("password")
    value["teacher_password"] = "ChangedBootstrap123!"
    path.write_text(json.dumps(value))
    bootstrap_demo(store, path)
    assert store.setting("password") == old
    assert verify_password("LocalDemoPassword123!", old)
    assert "LocalDemoPassword" not in store.db.execute("select detail from audit").fetchone()[0]


@pytest.mark.parametrize("alter", ["university", "weaken", "different_db"])
def test_bootstrap_refuses_wrong_database_or_weakened_policy(tmp_path, alter):
    path, value = config(tmp_path)
    target = tmp_path / "demo-agent" if alter != "different_db" else tmp_path / "real-user"
    if alter == "university": value["profile"]["moodle_url"] = "https://md.ksu.edu.kz/"
    if alter == "weaken": value["profile"]["policy"]["usb_block"] = False
    path.write_text(json.dumps(value))
    store = Store(target / "sergek.db")
    with pytest.raises(ValueError): bootstrap_demo(store, path)
    assert store.setting("profile") is None and store.setting("password") is None
