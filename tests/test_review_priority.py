import time
from pathlib import Path
from collections import deque
import cv2
import numpy as np
from backend.store import Store
from backend.config import Policy
from backend.vision import TemporalRules
from backend.engine import Engine
from backend.review_priority import review_summary

def signal(stamp, confidence=.6, phone=True):
    return {'phone':phone,'phone_sample_at':stamp,'phone_confidence':confidence,
            'faces':1,'quality':'good','gaze':'center','confidence':.9}

def test_one_second_phone_is_saved_from_independent_samples_and_not_cache():
    rules=TemporalRules();policy=Policy()
    assert rules.update(signal(0),policy,0)[0][0]=='phone_brief'
    assert rules.update(signal(0),policy,.2)==[]
    events=rules.update(signal(.4),policy,.4)
    assert events==[]
    assert rules.update(signal(.4),policy,.8)==[]
    rules.update(signal(.9,phone=False),policy,.9)
    assert rules.update(signal(1.1,phone=False),policy,1.1)==[]

def test_high_confidence_phone_gets_an_immediate_evidence_anchor():
    rules=TemporalRules();events=rules.update(signal(10,.9),Policy(),10)
    assert [k for k,d in events]==['phone_brief']
    assert events[0][1]['independent_samples']==1
    for t in [10.1,10.5,11,11.5]:assert not rules.update(signal(10,.9),Policy(),t)

def test_low_confidence_single_frame_is_not_saved_and_gap_does_not_extend_phone():
    rules=TemporalRules();assert rules.update(signal(0,.3),Policy(),0)==[]
    assert rules.update(signal(2.5,.3),Policy(),2.5)==[]

def test_two_weak_phone_like_frames_do_not_create_a_short_phone_event():
    rules=TemporalRules()
    assert rules.update(signal(0,.42),Policy(),0)==[]
    assert rules.update(signal(.5,.38),Policy(),.5)==[]

def test_gaze_warns_before_recording_and_disappears_on_return():
    rules=TemporalRules();policy=Policy(gaze_seconds=8)
    s={**signal(0,phone=False),'gaze':'left'}
    for stamp in [0,1,2,3]:assert rules.update(s,policy,stamp)==[]
    alert=rules.progress(policy,3)[0]
    assert alert['kind']=='gaze_side' and alert['seconds']==3 and not alert['saved']
    assert 0<alert['progress']<1
    rules.update({**s,'gaze':'center'},policy,3.1)
    assert rules.progress(policy,3.1)==[]

def test_brief_phone_evidence_survives_quick_finish_without_plaintext(tmp_path,monkeypatch):
    monkeypatch.setattr(Engine,'_load',lambda self:setattr(self,'loading',False))
    store=Store(tmp_path/'db');sid=store.create_session({'student':'Camera fixture','exam':'Short phone'})['id']
    store.update_session(sid,'active')
    engine=Engine(store,Path('models'),tmp_path,bytes(32));engine.sid=sid
    engine.policy=Policy(camera_required=False,microphone_required=False,screen_recording=False)
    now=time.monotonic();engine.last_analysis_at=now
    _,jpeg=cv2.imencode('.jpg',np.full((64,96,3),100,np.uint8))
    engine._collect_pending(now-.1,jpeg.tobytes())
    events=engine.rules.update(signal(now,.9),engine.policy,now)
    event=engine.record(*events[0]);assert event
    engine._collect_pending(now+.1,jpeg.tobytes())
    # Finish before the normal five-second post-roll has elapsed.
    engine.stop_camera();saved=store.event(event['id'])
    assert saved['media'] and len(engine.evidence(saved)['tracks']['camera'])>=2
    assert store.integrity(sid) and store.review_summaries([sid])[sid]['score']==5
    engine.writer.shutdown()

def test_priority_is_global_before_pagination_and_rebuilds_from_old_database(tmp_path):
    store=Store(tmp_path/'db');high=store.create_session({'student':'First','exam':'Exam'})['id']
    phone=store.add_event(high,'phone_detected',{})
    for i in range(102):store.create_session({'student':f'New {i}','exam':'Exam'})
    assert store.sessions(1,0,sort='priority')[0]['id']==high
    assert store.sessions(1,0,sort='newest')[0]['id']!=high
    # A reviewed observation leaves the queue without changing the event hash.
    store.review(phone['id'],'dismissed','Not a phone')
    assert store.review_summaries([high])[high]['score']==0 and store.integrity(high)
    store.db.execute('DELETE FROM review_metrics');store.db.commit()
    reopened=Store(tmp_path/'db');assert reopened.review_summaries([high])[high]['score']==0

def test_technical_blocks_and_system_failures_cannot_raise_student_priority(tmp_path):
    store=Store(tmp_path/'db');sid=store.create_session({'student':'Student','exam':'Exam'})['id']
    for kind,detail in [('navigation_blocked',{}),('application_closed',{'blocked':True}),('shortcut_blocked',{}),('session_interrupted',{})]:store.add_event(sid,kind,detail)
    result=store.review_summaries([sid])[sid]
    assert result['score']==result['pending_count']==0
    assert result['technical_count']==3 and result['system_count']==1

def test_brief_and_sustained_phone_are_one_priority_episode_and_one_review(tmp_path):
    store=Store(tmp_path/'db');sid=store.create_session({'student':'Student','exam':'Exam'})['id']
    a=store.add_event(sid,'phone_brief',{'episode_id':'phone-1','duration_seconds':0})
    b=store.add_event(sid,'phone_detected',{'episode_id':'phone-1'})
    result=store.review_summaries([sid])[sid]
    assert result['score']==10 and result['pending_episodes']==1 and result['pending_count']==2
    store.review(b['id'],'confirmed','Reviewed episode')
    assert store.event(a['id'])['verdict']=='confirmed'
    assert store.review_summaries([sid])[sid]['score']==0 and store.integrity(sid)

def test_priority_caps_at_100_and_explains_pending_reasons():
    events=[{'id':str(i),'kind':'phone_detected','detail':{'duration_seconds':10},'verdict':'pending'} for i in range(6)]
    result=review_summary(events)
    assert result['score']==100 and result['reasons']==[{'kind':'phone_detected','count':6,'points':120,'weight':20}]
