import time, base64, threading
from pathlib import Path
from collections import deque
import cv2
import numpy as np
from backend.engine import Engine
from backend.store import Store
from backend.config import Policy
from backend.vision import TemporalRules


class SyntheticCapture:
    def __init__(self, *args):
        self.closed = False

    def set(self, *args):
        pass

    def isOpened(self):
        return True

    def read(self):
        time.sleep(0.02)
        return True, np.full((240, 320, 3), 90, np.uint8)

    def release(self):
        self.closed = True


class SlowVision:
    ready = True
    error = ""
    calibration = {}
    identity = None

    def reset(self):
        pass

    def analyze(self, frame):
        time.sleep(0.15)
        return {"faces": 1, "quality": "good"}, frame


def test_slow_inference_does_not_hold_camera_capture(monkeypatch, tmp_path):
    monkeypatch.setattr(
        Engine,
        "_load",
        lambda self: (
            setattr(self, "vision", SlowVision()),
            setattr(self, "loading", False),
        ),
    )
    monkeypatch.setattr(cv2, "VideoCapture", SyntheticCapture)
    store = Store(tmp_path / "db.sqlite")
    sid = store.create_session({"student": "Synthetic", "exam": "Synthetic"})["id"]
    engine = Engine(store, Path("models"), tmp_path, bytes(32))
    try:
        engine.start_camera(sid, 0, Policy(screen_recording=False, microphone_required=False))
        time.sleep(0.9)
        status = engine.status()
        assert status["fps"] > 25
        assert 3 < status["analysis_fps"] < 10
        assert engine.frame_serial > 25
        assert engine.preview and engine.signals.get("faces") == 1
    finally:
        engine.stop_camera()
        engine.writer.shutdown()


def test_screen_and_camera_tracks_are_encrypted_and_processes_not_deduplicated(
    tmp_path,
):
    store = Store(tmp_path / "db.sqlite")
    sid = store.create_session({"student": "Synthetic", "exam": "Synthetic"})["id"]
    store.update_session(sid, "active")
    engine = Engine(store, Path("missing-models"), tmp_path, bytes(32))
    engine.sid = sid
    engine.policy = Policy(camera_required=False)
    stamp = time.monotonic()
    _, jpg = cv2.imencode(".jpg", np.full((80, 120, 3), 100, np.uint8))
    blob = jpg.tobytes()
    try:
        engine._collect_pending(stamp - 0.1, blob)
        engine._collect_pending(stamp - 0.1, blob, "screen")
        a = engine.record(
            "foreground_changed",
            {"pid": 1, "trusted":False,"prevention_active":False, "screen_jpeg": base64.b64encode(blob).decode()},
        )
        b = engine.record("foreground_changed", {"pid": 2, "trusted":False,"prevention_active":False})
        assert a and b
        engine._collect_pending(stamp + 6, blob, "screen")
        engine.stop_camera()
        saved = store.event(a["id"])
        assert "screen_jpeg" not in saved["detail"]
        clip = engine.evidence(saved)
        assert clip["tracks"]["camera"] and len(clip["tracks"]["screen"]) >= 2
        assert (tmp_path / "evidence" / saved["media"]).read_bytes().startswith(b"SG1")
    finally:
        engine.writer.shutdown()


def test_identity_event_waits_and_clears_when_comparison_is_unavailable():
    policy = Policy()
    rules = TemporalRules()
    signals = {"faces": 1, "quality": "good", "identity": {"state": "mismatch"}}
    assert rules.update(signals, policy, 0) == []
    assert rules.update(signals, policy, 1) == []
    assert (
        rules.update({**signals, "identity": {"state": "not_comparable"}}, policy, 1.5)
        == []
    )
    assert rules.update(signals, policy, 2) == []
    assert rules.update(signals, policy, 3) == []
    assert rules.update(signals, policy, 4) == []
    assert any(
        kind == "identity_mismatch" for kind, _ in rules.update(signals, policy, 4.6)
    )


def test_ten_capture_restarts_release_workers_and_clear_prior_buffers(monkeypatch,tmp_path):
    monkeypatch.setattr(Engine,'_load',lambda self:(setattr(self,'vision',SlowVision()),setattr(self,'loading',False)))
    monkeypatch.setattr(cv2,'VideoCapture',SyntheticCapture)
    store=Store(tmp_path/'db.sqlite');engine=Engine(store,Path('models'),tmp_path,bytes(32))
    try:
        for i in range(10):
            sid=store.create_session({'student':str(i),'exam':'Restart stress'})['id']
            engine.start_camera(sid,0,Policy(screen_recording=False,microphone_required=False))
            assert not engine.audio_frames and not engine.screen_frames
            time.sleep(.3)
            workers=[engine.thread,engine.analysis_thread]
            assert engine.frame_serial>5
            engine.stop_camera()
            assert all(not thread.is_alive() for thread in workers)
            assert not engine.pending and not engine.writes and engine.sid is None
    finally:engine.stop_camera();engine.writer.shutdown()
