import base64, io, time, wave
from pathlib import Path
import numpy as np
from backend.audio import Microphone, RATE
from backend.engine import Engine
from backend.config import Policy
from backend.store import Store


def test_real_vad_rejects_tone_noise_clicks_and_short_speech():
    events, chunks = [], []
    mic = Microphone(lambda *args: chunks.append(args), lambda *args: events.append(args))
    tone = (np.sin(np.arange(1600)*2*np.pi*440/RATE)*9000).astype(np.int16).tobytes()
    for i in range(100):
        mic.process(100+i/10, tone)
    assert not events
    rng = np.random.default_rng(42)
    for i in range(100):
        noise = rng.normal(0, 800, 1600).astype(np.int16)
        if i % 10 == 0: noise[50:65] = 15000
        mic.process(110+i/10, noise.tobytes())
    assert not events
    with wave.open(str(Path(__file__).parent / "fixtures/speech.wav")) as sound:
        speech = sound.readframes(sound.getnframes())
    for i in range(0, 64000, 3200):
        mic.process(120+i/32000, speech[i:i+3200])
    assert not events
    mic.process(125, bytes(3200))
    assert mic.since is None
    for i in range(0, len(speech), 3200):
        mic.process(130+i/32000, speech[i:i+3200])
    assert len(events) == 1 and events[0][0] == "sound_activity"
    assert events[0][1]["voiced_seconds"] >= 4 and events[0][1]["detector"] == "silero-vad-6.0"
    assert "Speaker and cheating are not determined" in events[0][1]["meaning"]


def test_one_speech_episode_does_not_repeat_every_fifteen_seconds():
    class CertainVoice:
        def probability(self, samples): return 0.99
        def reset(self): pass
    events=[]
    mic=Microphone(lambda *a: None,lambda *a: events.append(a),detector=CertainVoice())
    loud=np.full(1600,7000,np.int16).tobytes()
    for i in range(1000): mic.process(100+i/10,loud)
    assert len(events)==1
    for i in range(20): mic.process(200+i/10,bytes(3200))
    for i in range(60): mic.process(202+i/10,loud)
    assert len(events)==2


def test_single_microphone_dropout_is_not_a_permanent_device_failure():
    from types import SimpleNamespace
    mic=Microphone(lambda *a:None,lambda *a:None)
    mic.stream=SimpleNamespace(active=True)
    mic.thread=SimpleNamespace(is_alive=lambda:True)
    mic.last_frame=time.monotonic();mic.ready.set()
    mic.note_dropout()
    assert mic.status()["microphone_error"] == ""
    for _ in range(3):mic.note_dropout()
    assert "қайталанған" in mic.status()["microphone_error"]


def test_loud_non_speech_requires_duration_and_does_not_repeat():
    class NoVoice:
        def probability(self, samples): return 0.0
        def reset(self): pass
    events=[]; mic=Microphone(lambda *a:None,lambda *a:events.append(a),detector=NoVoice())
    loud=(np.sin(np.arange(1600)*2*np.pi*440/RATE)*26000).astype(np.int16).tobytes()
    for i in range(20):mic.process(100+i/10,loud)
    assert not events
    for i in range(20):mic.process(102+i/10,bytes(3200))
    for i in range(150):mic.process(104+i/10,loud)
    assert len(events)==1 and events[0][0]=='sustained_noise'
    assert events[0][1]['noise_seconds']>=4


def test_audio_evidence_is_encrypted_playable_and_buffers_do_not_cross_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(Engine,"_load",lambda self: None)
    store=Store(tmp_path/"db.sqlite")
    sid=store.create_session({"student":"Test", "exam":"Test"})["id"]
    store.update_session(sid,"active")
    engine=Engine(store,Path("models"),tmp_path,bytes(32))
    engine.start_camera(sid,0,Policy(camera_required=False,microphone_required=False,screen_recording=False))
    now=time.monotonic()
    pcm=(np.sin(np.arange(1600)*2*np.pi*440/RATE)*9000).astype(np.int16).tobytes()
    try:
        engine._collect_pending(now-.1,pcm,"audio")
        event=engine.record("sound_activity",{"level_dbfs":-15,"detector":"silero-vad-6.0"})
        engine._collect_pending(now+.1,pcm,"audio")
        engine.stop_camera()
        saved=store.event(event["id"])
        assert (tmp_path/"evidence"/saved["media"]).read_bytes().startswith(b"SG1")
        evidence=engine.evidence(saved)
        raw=base64.b64decode(evidence["audio"]["src"].split(",",1)[1])
        with wave.open(io.BytesIO(raw)) as sound:
            assert sound.getframerate()==16000 and sound.getnchannels()==1
            assert sound.getnframes()==3200 and sound.readframes(3200)==pcm+pcm
        assert evidence["frames"]==[] and evidence["audio"]["duration"]==.2
        next_sid=store.create_session({"student":"Other","exam":"Other"})["id"]
        engine.start_camera(next_sid,0,Policy(camera_required=False,microphone_required=False))
        assert not engine.audio_frames and not engine.pending
    finally:
        engine.stop_camera();engine.writer.shutdown()
