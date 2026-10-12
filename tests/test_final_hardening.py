import copy
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from backend.evidence_validation import validate_clip
from backend.signed_export import public_key,sign_report,verify_report
from backend.security import load_key
from backend.store import Store
from test_api import client,module


def clip(manifest=None,extra=None):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest or {'event_id':'a'*32,'tracks':{'camera':[{'file':'camera/0000.jpg','time':0}]},'primary':'camera'}))
        z.writestr('camera/0000.jpg',b'\xff\xd8\xffsample')
        for name,data in (extra or {}).items():z.writestr(name,data)
    return stream.getvalue()


def test_clip_valid():
    assert validate_clip(clip(),'a'*32)['primary']=='camera'


@pytest.mark.parametrize('change',['foreign','traversal','audio','tracks','time','nan','order','offset','primary','missing','zipbomb','duplicate'])
def test_hostile_clips(change):
    m={'event_id':'a'*32,'tracks':{'camera':[{'file':'camera/0000.jpg','time':0}]},'primary':'camera'};extra={}
    if change=='foreign':m['event_id']='b'*32
    if change=='traversal':extra['camera/../escape.jpg']=b'x'
    if change=='audio':m['audio']={'file':'manifest.json'}
    if change=='tracks':m['tracks']=['camera']
    if change=='time':m['tracks']['camera'][0]['time']='0'
    if change=='nan':m['tracks']['camera'][0]['time']=float('nan')
    if change=='order':m['tracks']['camera']=[{'file':'camera/0000.jpg','time':1},{'file':'camera/0000.jpg','time':0}]
    if change=='offset':m['event_offset']=-1
    if change=='primary':m['primary']={}
    if change=='missing':m['tracks']['camera'][0]['file']='camera/0001.jpg'
    if change=='zipbomb':extra['camera/0001.jpg']=b'x'*2_000_001
    if change=='duplicate':extra['camera/0000.jpg']=b'other'
    with pytest.raises(ValueError):validate_clip(clip(m,extra),'a'*32)


def test_concurrent_key_creation_and_signed_report(tmp_path):
    with ThreadPoolExecutor(max_workers=16) as pool:
        keys=list(pool.map(lambda _:load_key(tmp_path/'key'),range(64)))
    assert len(set(keys))==1
    store=Store(tmp_path/'db.sqlite');trusted=public_key(store)
    value=sign_report(store,{'session':'fixture','events':[1,2],'integrity_ok':True})
    assert verify_report(value,trusted)['events']==[1,2]
    forged=copy.deepcopy(value);forged['payload']['events'].pop()
    with pytest.raises(Exception):verify_report(forged,trusted)
    with pytest.raises(Exception):verify_report(value,'0'*64)


def test_paginated_teacher_search_and_counts(client):
    for i in range(205):module.store.create_session({'student':'Student '+str(i),'exam':'Exam'})
    first=client.get('/api/session-page').json();second=client.get('/api/session-page?offset=100').json()
    assert first['total']==205 and first['counts']['preflight']==205
    assert len(first['items'])==len(second['items'])==100
    assert not {s['id'] for s in first['items']} & {s['id'] for s in second['items']}
    assert client.get('/api/session-page?q=Student%20204').json()['total']==1
    assert client.get('/api/session-page?q=%25').json()['total']==0
    assert client.get('/api/session-page?limit=100000').status_code==422
    assert client.get('/api/session-page?offset=-1').status_code==422


def test_configuration_rejection_is_atomic(client):
    module.store.set_setting('moodle_public_key','a'*64)
    assert client.put('/api/integration/moodle',json={'public_key':'b'*64,'key':'k'*40}).status_code==403
    assert module.store.setting('moodle_public_key')=='a'*64


def test_non_ascii_headers_reject_without_server_error(client):
    module.store.set_secret('moodle_key','m'*40)
    assert client.get('/api/moodle/status?nonce=test',headers={b'x-sergek-moodle':b'\xff'}).status_code==403
    assert client.post('/api/hub/ingest',content=b'{}',headers={b'x-sergek-signature':b'\xff'}).status_code==403


def test_lost_submission_callback_reconciles_on_hub(client,monkeypatch):
    item=module.store.create_session({'remote':True,'platform':'moodle','exam_url':'https://localhost/mod/quiz/view.php?id=2','moodle':{'nonce':'n','userid':'42','quizid':'2'}})
    item=module.store.update_session(item['id'],'active')
    module.store.set_secret('moodle_key','k'*40)
    monkeypatch.setattr(module,'local_request',lambda *a,**k:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'state':'finished','nonce':'n','userid':'42','quizid':'2','attemptid':7}))
    module.reconcile_moodle(item)
    result=module.store.session(item['id'])
    assert result['status']=='active' and result['data']['stop_requested']
    assert result['data']['stop_reason']=='moodle_submitted'


def test_disk_reserve_rejects_new_session_before_mutation(client,monkeypatch):
    from backend import storage_budget
    from test_trust import prepare,send
    dev,p=prepare()
    monkeypatch.setattr(storage_budget.shutil,'disk_usage',lambda _:SimpleNamespace(free=10))
    assert send(client,dev,p).status_code==507
    assert module.store.session(p['session']['id']) is None
    assert module.store.db.execute('SELECT count(*) FROM received_packets').fetchone()[0]==0


def test_bad_media_does_not_leave_staging_or_claims(client):
    from test_trust import prepare,send
    import base64
    from test_hardening import event
    dev,p=prepare();e=event(p['session']['id']);p['events']=[e];p['evidence']={e['id']:base64.b64encode(clip({'event_id':e['id'],'tracks':{'camera':[{'file':'camera/0000.jpg','time':0}]}})).decode()}
    assert send(client,dev,p).status_code==422  # No chain hash commitment.
    assert not list((module.DATA/'staging').glob('*.tmp'))
    assert not module.store.session(p['session']['id'])


def test_terminal_control_ack_keeps_pending_media_retryable(client,monkeypatch,tmp_path):
    import httpx
    from backend.security import encrypt
    monkeypatch.setattr(module,'DATA',tmp_path)
    item=module.store.create_session({'platform':'local'});sid=item['id']
    event=module.store.add_event(sid,'phone_detected',{})
    module.store.attach_media(event['id'],event['id']+'.sg')
    folder=tmp_path/'evidence';folder.mkdir();(folder/(event['id']+'.sg')).write_bytes(encrypt(clip(),module.media_key))
    module.store.update_session(sid,'completed')
    module.store.set_secret('hub',{'enabled':True,'url':'https://hub.invalid','pairing_key':'k'*40})
    sent=[]
    def request(*args,**kwargs):
        packet=json.loads(kwargs['content']);sent.append(packet)
        status=507 if len(sent)==1 else 200
        return httpx.Response(status,json={'ok':True,'stop':False},request=httpx.Request('POST','https://hub.invalid'))
    monkeypatch.setattr(module,'local_request',request)
    assert module.sync_hub([sid]) is not False
    assert sent[0]['evidence'] and not sent[1]['evidence']
    assert not module.store.setting('synced_revision:'+sid)
    assert module.store.setting('synced_media:'+sid)==[]
    assert module.sync_hub([sid]) is not False
    assert event['id'] in module.store.setting('synced_media:'+sid)
    assert module.store.setting('synced_revision:'+sid)


def test_storage_stop_cannot_be_reported_as_success(client):
    item=module.store.create_session({'platform':'local'})
    module.store.update_session(item['id'],'active')
    module.apply_hub_stop(item,{'stop':True,'stop_reason':'evidence_storage_low'})
    assert module.store.session(item['id'])['status']=='interrupted'
