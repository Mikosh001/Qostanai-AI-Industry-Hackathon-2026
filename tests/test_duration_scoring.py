import time
import numpy as np
import pytest
from backend.observation_scoring import duration_points,event_points,SCALE
from backend.vision import TemporalRules
from backend.config import Policy
from backend.review_priority import review_summary
from backend.store import Store
from backend.audio import Microphone

def signal(t,**extra):
    return {'faces':1,'quality':'good','gaze':'center','confidence':.9,
            'phone':False,'phone_sample_at':t,'phone_confidence':.8,**extra}

@pytest.mark.parametrize('kind,duration,points',[
 ('phone_brief',0,5),('phone_detected',1.999,5),('phone_detected',2,10),
 ('phone_detected',4.999,10),('phone_detected',5,15),('phone_detected',9.999,15),('phone_detected',10,20),
 ('multiple_faces',2.999,0),('multiple_faces',3,2),('multiple_faces',90,2),
 ('identity_mismatch',2.999,0),('identity_mismatch',3,10),('identity_mismatch',5,15),
 ('gaze_side',4.999,0),('gaze_side',5,3),('gaze_down',10,5),('gaze_side',20,10),
 ('sustained_noise',0,1),('sound_activity',90,1)])
def test_exact_requested_duration_boundaries(kind,duration,points):
    assert duration_points(kind,duration)==points

def observe(rules,seconds,**extra):
    events=[]
    for step in range(int(seconds*10)+1):
        t=step/10;events.extend(rules.update(signal(t,**extra),Policy(),t))
    return events

def as_events(rows):
    return [{'id':str(i),'kind':k,'detail':d,'verdict':'pending'} for i,(k,d) in enumerate(rows)]

def test_phone_is_immediate_then_upgrades_once_per_tier_not_every_frame():
    rules=TemporalRules();rows=observe(rules,30,phone=True)
    assert [d['points'] for k,d in rows]==[5,10,15,20]
    assert [d['points_delta'] for k,d in rows]==[5,5,5,5]
    assert len({d['episode_id'] for k,d in rows})==1
    result=review_summary(as_events(rows))
    assert result['score']==20 and result['pending_episodes']==1

def test_cached_phone_cannot_upgrade_and_a_camera_gap_restarts_duration():
    r=TemporalRules();first=r.update(signal(0,phone=True),Policy(),0)
    assert first[0][1]['points']==5
    for t in [.5,1,1.5,2,2.5,3]:assert not r.update(signal(0,phone=True),Policy(),t)
    fresh=r.update(signal(7,phone=True),Policy(),7)
    assert fresh[0][1]['points']==5 and fresh[0][1]['episode_id']!=first[0][1]['episode_id']

def test_candidate_warns_immediately_but_weak_frames_do_not_add_points():
    r=TemporalRules()
    for t in [0,.4,.8]:assert not r.update(signal(t,phone=True,phone_confidence=.42),Policy(),t)
    assert r.progress(Policy(),.8)[0]['points']==0
    confirmed=r.update(signal(1,phone=True,phone_confidence=.6),Policy(),1)
    assert confirmed[0][1]['points']==5 and confirmed[0][1]['duration_seconds']==0

def test_two_second_passerby_warns_but_never_adds_points():
    r=TemporalRules();assert not observe(r,2.9,faces=2)
    assert r.progress(Policy(),2.9)[0]['kind']=='multiple_faces'
    assert not r.update(signal(3),Policy(),3)
    assert r.progress(Policy(),3)==[]
    r=TemporalRules();rows=observe(r,15,faces=2)
    assert len(rows)==1 and rows[0][1]['points']==2

def test_identity_requires_one_good_face_and_does_not_double_count_gaze():
    r=TemporalRules();rows=observe(r,10,identity={'state':'mismatch'},gaze='left')
    assert [(k,d['points']) for k,d in rows]==[('identity_mismatch',10),('identity_mismatch',15)]
    r=TemporalRules();rows=observe(r,10,faces=2,identity={'state':'mismatch'})
    assert [(k,d['points']) for k,d in rows]==[('multiple_faces',2)]

def test_gaze_side_and_down_share_one_episode_and_warn_from_first_frame():
    r=TemporalRules();rows=[]
    for i in range(251):
        t=i/10;rows.extend(r.update(signal(t,gaze='left' if i%2 else 'down'),Policy(),t))
        if i==0:assert r.progress(Policy(),t)[0]['points']==0
    assert [d['points'] for k,d in rows]==[3,5,10]
    assert review_summary(as_events(rows))['score']==10
    r.update(signal(26),Policy(),26);assert not r.progress(Policy(),26)

def test_all_stage_decisions_propagate_and_old_cache_is_recalculated(tmp_path):
    store=Store(tmp_path/'db');sid=store.create_session({'student':'Fixture','exam':'Tier test'})['id']
    rows=observe(TemporalRules(),20,gaze='left');events=[store.add_event(sid,k,d) for k,d in rows]
    assert store.review_summaries([sid])[sid]['score']==10
    store.review(events[0]['id'],'dismissed','Reviewed whole episode')
    assert all(e['verdict']=='dismissed' for e in store.events(sid))
    assert store.review_summaries([sid])[sid]['score']==0 and store.integrity(sid)
    store.db.execute("UPDATE review_metrics SET summary=?",('{"scale":"review-priority/1"}',));store.db.commit()
    store.db.close();store=Store(tmp_path/'db')
    assert store.review_summaries([sid])[sid]['scale']==SCALE

class NoVoice:
    def probability(self,samples):return 0
    def reset(self):pass

def test_noise_warns_immediately_scores_once_and_preflight_cannot_consume_exam_episode():
    events=[];mic=Microphone(lambda *a:None,lambda *a:events.append(a),detector=NoVoice())
    loud=np.full(1600,20000,np.int16).tobytes()
    mic.process(100,loud)
    assert mic.feedback(100)[0]['points']==0 and not events
    for i in range(1,100):mic.process(100+i/10,loud)
    assert len(events)==1 and events[0][1]['points']==1
    first=events[0][1]['episode_id'];mic.arm_exam()
    for i in range(10):mic.process(110+i/10,loud)
    assert len(events)==2 and events[1][1]['episode_id']!=first
    for i in range(60):mic.process(111+i/10,bytes(3200))
    assert not mic.feedback(117)
    for i in range(10):mic.process(117+i/10,loud)
    assert len(events)==3

def test_incoming_points_cannot_override_duration_schedule():
    event={'kind':'gaze_side','detail':{'duration_seconds':1,'points':100}}
    assert event_points(event)==0

@pytest.mark.parametrize('episode',[{},[],['id'],'x'*129])
def test_invalid_episode_ids_cannot_break_or_merge_the_queue(episode):
    rows=[{'id':str(i),'kind':'phone_brief','detail':{'episode_id':episode},'verdict':'pending'} for i in range(2)]
    result=review_summary(rows)
    assert result['score']==10 and result['pending_episodes']==2

def test_short_audio_pauses_do_not_fill_the_scale():
    events=[];mic=Microphone(lambda *a:None,lambda *a:events.append(a),detector=NoVoice())
    loud=np.full(1600,20000,np.int16).tobytes()
    for burst in range(4):
        for i in range(10):mic.process(100+burst*3+i/10,loud)
        for i in range(20):mic.process(101+burst*3+i/10,bytes(3200))
    assert len(events)==1

def test_simultaneous_progressive_events_keep_evidence_and_hashes(tmp_path,monkeypatch):
    from backend.engine import Engine
    from pathlib import Path
    import cv2
    monkeypatch.setattr(Engine,'_load',lambda self:setattr(self,'loading',False))
    store=Store(tmp_path/'db');sid=store.create_session({'student':'Fixture','exam':'Combined capture'})['id']
    store.update_session(sid,'active');engine=Engine(store,Path('models'),tmp_path,bytes(32));engine.sid=sid
    engine.policy=Policy(camera_required=False,microphone_required=False,screen_recording=False)
    base=time.monotonic();clock=[base]
    monkeypatch.setattr('backend.engine.time.monotonic',lambda:clock[0])
    _,jpeg=cv2.imencode('.jpg',np.zeros((32,48,3),np.uint8))
    for step in range(221):
        clock[0]=base+step/10
        engine._collect_pending(clock[0],jpeg.tobytes())
        for kind,detail in engine.rules.update(signal(clock[0],phone=True,gaze='left'),engine.policy,clock[0]):engine.record(kind,detail)
    engine.stop_camera();engine.writer.shutdown()
    observations=[e for e in store.events(sid) if e['kind'] in {'phone_brief','phone_detected','gaze_side'}]
    assert len(observations)==7 and all(e['media'] for e in observations)
    assert not engine.evidence_error and store.integrity(sid)
    result=store.review_summaries([sid])[sid]
    assert result['score']==30 and result['pending_episodes']==2

def test_global_queue_preserves_priority_above_the_visual_scale_limit(tmp_path):
    store=Store(tmp_path/'db')
    first=store.create_session({'student':'Older','exam':'Queue'})['id']
    for _ in range(6):store.add_event(first,'phone_detected',{'duration_seconds':10})
    second=store.create_session({'student':'Newer','exam':'Queue'})['id']
    for _ in range(5):store.add_event(second,'phone_detected',{'duration_seconds':10})
    store.add_event(second,'phone_detected',{'duration_seconds':2})
    assert store.sessions(limit=1,sort='priority')[0]['id']==first
    assert store.review_summaries([first])[first]['total_points']==120

def test_evidence_backlog_remains_bounded_and_cannot_fail_silently(tmp_path,monkeypatch):
    from backend.engine import Engine
    from pathlib import Path
    from concurrent.futures import Future
    monkeypatch.setattr(Engine,'_load',lambda self:setattr(self,'loading',False))
    store=Store(tmp_path/'db');sid=store.create_session({'student':'Fixture','exam':'Bounded queue'})['id']
    store.update_session(sid,'active');engine=Engine(store,Path('models'),tmp_path,bytes(32))
    engine.sid=sid;engine.policy=Policy();engine.writes=[Future() for _ in range(8)]
    engine.record('phone_brief',{'episode_id':'bounded','points':5})
    assert engine.evidence_error and not engine.pending
    assert store.session(sid)['data']['evidence_incomplete']
    engine.writer.shutdown()

def test_brief_phone_occlusion_reuses_episode_without_charging_hidden_time():
    r=TemporalRules();first=r.update(signal(0,phone=True),Policy(),0)[0]
    for t in [.5,1]:assert not r.update(signal(t,phone=True),Policy(),t)
    for t in [1.1,1.6]:assert not r.update(signal(t,phone=False),Policy(),t)
    assert not r.update(signal(2.2,phone=True),Policy(),2.2)
    assert r.progress(Policy(),2.2)[0]['seconds']==1.1
    assert not r.update(signal(2.7,phone=True),Policy(),2.7)
    event=r.update(signal(3.2,phone=True),Policy(),3.2)[0]
    assert event[1]['points']==10 and event[1]['episode_id']==first[1]['episode_id']
