from backend.event_policy import annotate
from backend.reports import payload
from backend.store import Store
from backend.engine import Engine
from backend.config import Policy
from pathlib import Path
import pytest


def test_legacy_noise_and_navigation_do_not_become_review_flags_or_change_hashes(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    session=store.create_session({'student':'Fixture','exam':'Fixture'})
    sid=session['id']
    navigation=store.add_event(sid,'navigation_blocked',{'host':'cdn.jsdelivr.net'})
    noise=store.add_event(sid,'sound_activity',{'level_dbfs':-25})
    voice=store.add_event(sid,'sound_activity',{'detector':'silero-vad-6.0','voiced_seconds':4})
    result=payload(store,sid)
    assert [e['requires_review'] for e in result['events']]==[False,False,True]
    assert result['integrity_ok'] and result['events'][0]['hash']==navigation['hash']
    assert store.integrity(sid)


def test_technical_burst_creates_no_camera_audio_or_screen_evidence_tasks(tmp_path,monkeypatch):
    monkeypatch.setattr(Engine,'_load',lambda self:None)
    store=Store(tmp_path/'db.sqlite');sid=store.create_session({'student':'Fixture','exam':'Fixture'})['id']
    store.update_session(sid,'active');engine=Engine(store,Path('models'),tmp_path,bytes(32))
    engine.sid=sid;engine.policy=Policy(camera_required=False,microphone_required=False,screen_recording=False)
    try:
        for i in range(200): engine.record(['foreground_changed','application_closed','remote_control_blocked'][i%3],{'pid':i,'trusted':True,'blocked':True})
        assert len(store.events(sid))==200
        assert not engine.pending and not engine.writes
        assert all(not annotate(e)['requires_review'] for e in store.events(sid))
        event=engine.record('identity_mismatch',{'duration_seconds':3})
        assert event and len(engine.pending)==1
    finally:engine.stop_camera();engine.writer.shutdown()


@pytest.mark.parametrize("kind,detail", [
    ("application_closed", {"phase":"active", "blocked":True}),
    ("remote_control_blocked", {"phase":"active", "restarted_then_stopped":True}),
    ("shortcut_blocked", {"blocked":True}),
    ("navigation_blocked", {}), ("forbidden_process", {"blocked":True,"phase":"active"}),
    ("remote_control", {"blocked":True,"phase":"active"}),
])
def test_prevented_actions_are_technical_and_not_accusations(kind, detail):
    assert not annotate({"kind":kind,"detail":detail})['requires_review']


def test_actual_untrusted_foreground_and_loud_noise_require_review():
    assert annotate({"kind":"foreground_changed","detail":{"trusted":False,"prevention_active":False,"phase":"active"}})['requires_review']
    assert not annotate({"kind":"foreground_changed","detail":{"trusted":False,"prevention_active":True,"phase":"active"}})['requires_review']
    assert not annotate({"kind":"foreground_changed","detail":{"trusted":True,"phase":"active"}})['requires_review']
    assert annotate({"kind":"sustained_noise","detail":{}})['requires_review']
