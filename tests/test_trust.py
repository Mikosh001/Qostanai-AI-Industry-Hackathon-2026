"""Cross-device, forged-identity, recovery and cursor protocol regression tests.

These deliberately hostile clients own their device credentials. None operates
real USB/services/cameras on the workstation.
"""
import base64
import copy
import hashlib
import hmac
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from backend import trust
from backend.security import canonical, sign_launch as old_sign
from backend.sync_protocol import acknowledge
from test_api import client, module, sign_launch
from test_hardening import event


def prepare():
    dev=trust.enroll(module.store,'QA device')
    payload={'exp':time.time()+300,'nonce':uuid.uuid4().hex,'userid':'42','quizid':'17',
             'url':'https://localhost/mod/quiz/view.php?id=100','mode':'monitor','device_id':dev['device_id']}
    token=sign_launch(payload,'not-a-signing-key')
    claims=trust.issue(module.store,token)
    packet={'packet_id':uuid.uuid4().hex,'sent_at':time.time(),'launch_token':token,
            'session':{'id':uuid.uuid4().hex,'created':'2026-10-12T00:00:00+00:00','started':None,'ended':None,'status':'preflight',
                       'data':{'platform':'moodle','mode':'monitor','exam_url':payload['url'],'moodle':claims,'moodle_prepared':True}},
            'events':[],'evidence':{},'cursor':0,'cursor_head':'0'*64}
    return dev,packet


def send(client,dev,packet,path='/api/hub/ingest'):
    raw=canonical(packet)
    return client.post(path,content=raw,headers={'x-sergek-device':dev['device_id'],
           'x-sergek-signature':hmac.new(dev['device_key'].encode(),raw,hashlib.sha256).hexdigest()})


def lease(packet,count=0,head='0'*64):
    return {'packet_id':uuid.uuid4().hex,'sent_at':time.time(),'session_id':packet['session']['id'],
            'anchor':{'count':count,'head':head}}


def test_pairing_key_cannot_forge_moodle_identity(client):
    dev,p=prepare()
    module.store.set_setting('hub_receive_key','h'*40)
    raw=canonical(p)
    r=client.post('/api/hub/ingest',content=raw,headers={'x-sergek-signature':hmac.new(b'h'*40,raw,hashlib.sha256).hexdigest()})
    assert r.status_code==403
    assert module.store.session(p['session']['id']) is None


@pytest.mark.parametrize('field,bad',[('nonce','not-issued'),('userid','999'),('quizid','18')])
def test_device_key_cannot_rewrite_server_identity(client,field,bad):
    dev,p=prepare();p['session']['data']['moodle'][field]=bad
    assert send(client,dev,p).status_code==403
    assert not module.store.sessions()


@pytest.mark.parametrize('change',['missing','tampered','unissued','legacy','mode','url'])
def test_reject_invalid_grant_before_binding(client,change):
    dev,p=prepare()
    if change=='missing':p.pop('launch_token')
    elif change=='tampered':p['launch_token']=p['launch_token'][:-5]+'aaaaa'
    elif change=='unissued':
        module.store.db.execute('DELETE FROM issued_grants');module.store.db.commit()
    elif change=='legacy':p['launch_token']=old_sign({'exp':time.time()+60,'nonce':'x','userid':'42','quizid':'17','url':'https://localhost/'},'key')
    elif change=='mode':p['session']['data']['mode']='strict'
    elif change=='url':p['session']['data']['exam_url']='https://evil.example/'
    assert send(client,dev,p).status_code in (403,422)
    assert not module.store.sessions()


def test_bind_once_and_revoke_immediately_disables_moodle(client):
    dev,p=prepare();assert send(client,dev,p).json()['prepared']
    other=trust.enroll(module.store,'Other device')
    p['packet_id']=uuid.uuid4().hex
    assert send(client,other,p).status_code==403
    p['session']['id']=uuid.uuid4().hex
    assert send(client,other,p).status_code==403
    original=module.store.sessions()[0]
    module.store.set_secret('moodle_key','m'*40)
    assert client.get('/api/moodle/status',params={'nonce':original['data']['moodle']['nonce']},headers={'x-sergek-moodle':'m'*40}).json()['prepared']
    assert client.delete('/api/integration/devices/'+dev['device_id']).status_code==200
    assert send(client,dev,lease({'session':original}),'/api/hub/lease').status_code==403
    assert not client.get('/api/moodle/status',params={'nonce':original['data']['moodle']['nonce']},headers={'x-sergek-moodle':'m'*40}).json()['prepared']


def test_incremental_upload_preserves_review_and_rejects_cursor_replay(client):
    dev,p=prepare();sid=p['session']['id'];a=event(sid);p['events']=[a]
    r=send(client,dev,p);assert r.status_code==200,r.text
    assert r.json()['anchor']=={'count':1,'head':a['hash']}
    module.store.review(a['id'],'dismissed','Phone-shaped notebook')
    p.update(packet_id=uuid.uuid4().hex,cursor=1,cursor_head=a['hash'],events=[event(sid,previous=a['hash'])])
    assert send(client,dev,p).status_code==200
    assert module.store.event(a['id'])['note']=='Phone-shaped notebook'
    p['packet_id']=uuid.uuid4().hex
    assert send(client,dev,p).status_code==409
    assert len(module.store.events(sid))==2 and module.store.integrity(sid)


def test_failed_event_transaction_does_not_consume_grant(client):
    dev,p=prepare();p['events']=[event(p['session']['id'])];p['events'][0]['hash']='f'*64
    assert send(client,dev,p).status_code==422
    row=module.store.db.execute('SELECT session_id FROM issued_grants').fetchone()
    assert row[0] is None
    p['events']=[]
    assert send(client,dev,p).status_code==200


def test_lease_is_small_independent_and_replay_protected(client):
    dev,p=prepare();assert send(client,dev,p).status_code==200
    q=lease(p)
    assert len(canonical(q))<500
    assert send(client,dev,q,'/api/hub/lease').json()['prepared']
    assert send(client,dev,q,'/api/hub/lease').status_code==409
    q=lease(p);q['sent_at']=time.time()-31
    assert send(client,dev,q,'/api/hub/lease').status_code==422
    q=lease(p);q['session_id']='f'*32
    assert send(client,dev,q,'/api/hub/lease').status_code==403


def test_server_anchor_rejects_tail_deletion_and_bad_head(client):
    dev,p=prepare();a=event(p['session']['id']);p['events']=[a]
    assert send(client,dev,p).status_code==200
    for count,head in [(0,'0'*64),(1,'f'*64)]:
        assert send(client,dev,lease(p,count,head),'/api/hub/lease').status_code==409
    assert send(client,dev,lease(p,1,a['hash']),'/api/hub/lease').status_code==200


def test_local_tail_deletion_is_no_longer_integrity_true(client):
    s=module.store.create_session({})['id']
    for i in range(3):module.store.add_event(s,'phone_detected',{'i':i})
    events=module.store.events(s)
    acknowledge(module.store,s,{'anchor':{'count':3,'head':events[-1]['hash']}})
    module.store.db.execute('DELETE FROM events WHERE id=?',(events[-1]['id'],));module.store.db.commit()
    assert not module.store.integrity(s)


def test_device_credentials_are_encrypted_and_not_returned_by_listing(client):
    dev,p=prepare()
    raw=' '.join(r[0] for r in module.store.db.execute('SELECT value FROM settings'))
    assert dev['device_key'] not in raw
    result=client.get('/api/integration/devices').text
    assert dev['device_id'] in result and dev['device_key'] not in result
    assert client.put('/api/integration/moodle',json={'key':'s'*40}).status_code==403


def test_new_devices_require_teacher_and_central_hub(client,monkeypatch):
    assert client.post('/api/integration/devices',json={'name':'QA'}).status_code==409
    monkeypatch.setenv('SERGEK_SERVICE_ROLE','hub')
    assert client.post('/api/integration/devices',json={'name':'QA'}).status_code==200
    client.post('/api/auth/logout')
    assert client.post('/api/integration/devices',json={'name':'Intruder'}).status_code==401


def test_parallel_device_attempt_binding_is_atomic(client):
    dev,p=prepare();other=trust.enroll(module.store,'Other')
    q=copy.deepcopy(p);q['session']['id']=uuid.uuid4().hex;q['packet_id']=uuid.uuid4().hex
    def go(values):
        device,packet=values
        try:module.ingest_packet(canonical(packet),device['device_id']);return 200
        except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(go,[(dev,p),(other,q)]))
    assert sorted(results)==[200,403]
    assert len(module.store.sessions())==1

