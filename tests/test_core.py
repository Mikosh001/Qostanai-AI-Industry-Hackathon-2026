import json, time, hashlib, io, zipfile
from pathlib import Path
import numpy as np
import pytest
from cryptography.exceptions import InvalidTag
from backend.security import (
    hash_password,
    verify_password,
    encrypt,
    decrypt,
    sign_launch,
    verify_launch,
    canonical,
)
from backend.store import Store
from backend.vision import TemporalRules, Vision
from backend.config import Policy
from backend.engine import Engine


def test_password_and_authenticated_encryption():
    encoded = hash_password("A strong teacher password")
    assert verify_password("A strong teacher password", encoded)
    assert not verify_password("wrong", encoded)
    key = bytes(range(32))
    blob = encrypt(b"private frames", key)
    assert decrypt(blob, key) == b"private frames"
    with pytest.raises(InvalidTag):
        decrypt(blob[:-1] + bytes([blob[-1] ^ 1]), key)


def test_signed_launch_expiry_and_tampering():
    payload = {
        "exp": time.time() + 60,
        "nonce": "n",
        "userid": "42",
        "quizid": "5",
        "url": "https://md.ksu.edu.kz/mod/quiz/view.php?id=1",
    }
    token = sign_launch(payload, "key")
    assert verify_launch(token, "key")["userid"] == "42"
    with pytest.raises(ValueError):
        verify_launch(token + "0", "key")
    payload["exp"] = time.time() - 1
    with pytest.raises(ValueError):
        verify_launch(sign_launch(payload, "key"), "key")


def test_temporal_rules_are_duration_based_and_deduplicate():
    rules = TemporalRules()
    policy = Policy(phone_seconds=1)
    signals = {"phone": True, "faces": 1, "quality": "good", "gaze": "center"}
    assert rules.update(signals, policy, 0) == []
    assert rules.update(signals, policy, 0.5) == []
    events = rules.update(signals, policy, 1.2)
    assert events[0][0] == "phone_detected"
    assert rules.update(signals, policy, 1.8) == []
    rules.update({**signals, "phone": False}, policy, 2)
    assert rules.update(signals, policy, 2.1) == []  # Brief dropout does not duplicate a phone.
    assert rules.update(signals, policy, 3.2) == []
    rules.update({**signals, "phone": False}, policy, 3.3)
    rules.update({**signals, "phone": False}, policy, 4.4)
    assert rules.update(signals, policy, 4.5) == []
    assert rules.update(signals, policy, 5.0) == []
    assert rules.update(signals, policy, 5.6)[0][0] == "phone_detected"


def test_phone_cached_detection_is_not_independent_evidence_and_brief_miss_survives():
    rules = TemporalRules(); policy = Policy(phone_seconds=2)
    signal = {"phone":True,"faces":1,"quality":"good","phone_sample_at":1}
    for stamp in [0, .4, .8, 1.2, 1.6, 2.0]:
        assert not rules.update(signal,policy,stamp)
    assert not rules.update({**signal,"phone_sample_at":2},policy,2.1)
    assert rules.update({**signal,"phone_sample_at":3},policy,2.6)[0][0] == 'phone_detected'
    rules = TemporalRules()
    for stamp,phone in [(0,True),(.5,True),(1,False),(1.1,True),(1.6,True)]:
        assert not rules.update({**signal,"phone":phone,"phone_sample_at":stamp},policy,stamp)
    assert rules.update({**signal,"phone_sample_at":2.1},policy,2.1)[0][0] == 'phone_detected'
    rules = TemporalRules()
    for stamp,phone in [(0,True),(.9,True),(1.8,False)]:
        assert not rules.update({**signal,"phone":phone,"phone_sample_at":stamp},policy,stamp)
    assert rules.update({**signal,"phone_sample_at":2.7},policy,2.7)[0][0] == 'phone_detected'


def test_camera_gap_does_not_inflate_duration_or_accuse_paper_use():
    rules = TemporalRules()
    signals = {"gaze": "down", "quality": "good", "faces": 1}
    assert rules.update(signals, Policy(), 0) == []
    assert rules.update(signals, Policy(), 10) == []
    for stamp in range(11, 17):
        assert not rules.update(signals, Policy(paper_allowed=True), stamp)


def test_event_chain_reviews_and_answers_persist(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    session = store.create_session(
        {"student": "Student", "exam": "Exam", "platform": "local"}
    )
    a = store.add_event(session["id"], "usb_connected", {"id": "device"})
    b = store.add_event(session["id"], "phone_detected", {"confidence": 0.8})
    assert b["previous_hash"] == a["hash"] and store.integrity(session["id"])
    store.review(a["id"], "dismissed", "Allowed device")
    assert store.integrity(session["id"])
    store.save_answer(session["id"], "1", 2)
    reopened = Store(tmp_path / "db.sqlite")
    assert reopened.answers(session["id"]) == {"1": 2}
    store.db.execute(
        "UPDATE events SET detail=? WHERE id=?", ('{"changed":true}', a["id"])
    )
    store.db.commit()
    assert not store.integrity(session["id"])


def test_evidence_roundtrip_without_plaintext_files(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    sid = store.create_session({"student": "Student", "exam": "Exam"})["id"]
    event = store.add_event(sid, "phone_detected", {})
    engine = Engine.__new__(Engine)
    engine.data = tmp_path
    engine.key = bytes(range(32))
    engine.store = store
    engine._save_evidence(
        {
            "id": event["id"],
            "frames": [(10, b"jpeg-a"), (10.2, b"jpeg-b")],
            "started": 10.1,
        }
    )
    saved = store.event(event["id"])
    assert saved["media"]
    assert list((tmp_path / "evidence").glob("*"))[0].suffix == ".sg"
    clip = engine.evidence(saved)
    assert len(clip["frames"]) == 2
    assert clip["event_offset"] == 0.1


def test_real_models_load_and_process_blank_frame():
    models = Path(__file__).resolve().parent.parent / "models"
    if not (models / "yolo11n.onnx").exists():
        pytest.skip("Run download_models.py")
    vision = Vision(models)
    assert vision.ready, vision.error
    result, image = vision.analyze(np.full((480, 640, 3), 120, np.uint8))
    assert result["faces"] == 0 and not result["phone"] and image.shape == (480, 640, 3)
    vision.close()
