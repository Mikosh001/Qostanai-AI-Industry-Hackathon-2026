import os, tempfile, time, json, hmac, hashlib

os.environ["SERGEK_DATA"] = tempfile.mkdtemp(prefix="sergek-api-test-")
os.environ["SERGEK_DESKTOP_KEY"] = "test-desktop-key"
import pytest
import httpx
from fastapi.testclient import TestClient
from backend import app as module
from backend.store import Store
from backend.security import sign_launch, canonical


class TestCamera:
    """API tests inject a camera; actual models are tested separately in test_core."""

    def __init__(self):
        self.sid = None
        self.signals = {"faces": 1, "quality": "good"}
        self.vision = None

    def start_camera(self, sid, index, policy):
        self.sid = sid

    def stop_camera(self):
        self.sid = None

    def status(self):
        return {
            "models_ready": False,
            "loading": False,
            "camera_running": False,
            "calibration": {},
        }

    def snapshot(self, include_preview=True):
        return {"signals": self.signals, "preview": None, "status": self.status()}

    def start_recording(self):
        pass

    def record(self, kind, detail):
        return module.store.add_event(self.sid, kind, detail)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "store", Store(tmp_path / "db.sqlite"))
    monkeypatch.setattr(module, "engine", TestCamera())
    monkeypatch.setattr(module, "teacher_tokens", {})
    monkeypatch.setattr(module, "student_tokens", {})
    monkeypatch.setattr(module, "login_attempts", {})
    value = TestClient(module.app)
    assert (
        value.post(
            "/api/setup",
            json={"password": "StrongTeacher123!"},
            headers={"x-sergek-desktop": "test-desktop-key"},
        ).status_code
        == 200
    )
    assert (
        value.post(
            "/api/auth/login", json={"password": "StrongTeacher123!"}
        ).status_code
        == 200
    )
    p = value.get("/api/profile").json()
    p["policy"]["camera_required"] = False
    p["policy"]["screen_recording"] = False
    p["policy"]["microphone_required"] = False
    p["exam_mode"] = "monitor"
    assert value.put("/api/profile", json=p).status_code == 200
    return value


def create(client, **extra):
    if "mode" in extra:
        p = client.get("/api/profile").json()
        p["exam_mode"] = extra["mode"]
        assert client.put("/api/profile", json=p).status_code == 200
    result = client.post(
        "/api/sessions",
        headers={"x-sergek-desktop": "test-desktop-key"},
        json={
            "student": "Student",
            "exam": "Exam",
            "consent": True,
            "mode": "monitor",
            **extra,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def headers(value):
    return {"Authorization": "Bearer " + value["token"], "x-sergek-desktop": "test-desktop-key"}


def test_auth_csrf_and_desktop_separation(client):
    assert (
        client.post(
            "/api/sessions", json={"student": "AB", "exam": "CD", "consent": True}
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/profile", json={}, headers={"origin": "https://evil.example"}
        ).status_code
        == 403
    )
    client.post("/api/auth/logout")
    assert client.get("/api/sessions").status_code == 401
    for _ in range(5):
        assert (
            client.post("/api/auth/login", json={"password": "wrong"}).status_code
            == 401
        )
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 429


def test_local_exam_answers_report_review_and_delete(client):
    value = create(client)
    sid = value["session"]["id"]
    h = headers(value)
    assert client.get(f"/api/student/{sid}/snapshot").status_code == 401
    assert (
        client.post(
            f"/api/student/{sid}/start", headers=h, json={"guard": {}, "desktop": {}}
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/student/{sid}/answer",
            headers=h,
            json={"question_id": "1", "answer": 1},
        ).status_code
        == 200
    )
    event = client.post(
        f"/api/student/{sid}/event",
        headers=h,
        json={"kind": "usb_connected", "detail": {"blocked": False}},
    ).json()
    assert (
        client.patch(
            "/api/events/" + event["id"],
            json={"verdict": "dismissed", "note": "Test device"},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/student/{sid}/finish", headers=h, json={}).status_code == 200
    )
    report = client.get(f"/api/sessions/{sid}/report/json").json()
    assert report["answers"] == {"1": 1} and report["integrity_ok"]
    pdf = client.get(f"/api/sessions/{sid}/report/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    from io import BytesIO
    from pypdf import PdfReader
    for language, title in [("kk", "сессия есебі"), ("ru", "отчёт о сессии"), ("en", "session report")]:
        pdf = client.get(f"/api/sessions/{sid}/report/pdf?lang={language}")
        assert pdf.status_code == 200
        assert title in PdfReader(BytesIO(pdf.content)).pages[0].extract_text()
    assert client.get(f"/api/sessions/{sid}/report/pdf?lang=invalid").status_code == 422
    assert (
        client.put(
            f"/api/student/{sid}/answer",
            headers=h,
            json={"question_id": "1", "answer": 2},
        ).status_code
        == 409
    )
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_strict_fails_closed_without_native_enforcement(client):
    value = create(client, mode="strict")
    sid = value["session"]["id"]
    result = client.post(
        f"/api/student/{sid}/start",
        headers=headers(value),
        json={"guard": {"storage_policy_applied": True}, "desktop": {"displays": 1}},
    )
    assert result.status_code == 409 and "USB" in result.text
    assert module.store.session(sid)["status"] == "preflight"


def test_photo_required_without_four_direction_calibration(client, monkeypatch):
    p = client.get("/api/profile").json()
    p["policy"]["camera_required"] = True
    client.put("/api/profile", json=p)
    status = {
        "models_ready": True,
        "camera_running": True,
        "identity_enrolled": False,
        "calibration": {},
    }
    monkeypatch.setattr(module.engine, "status", lambda: status)
    value = create(client)
    sid = value["session"]["id"]
    result = client.post(f"/api/student/{sid}/start", headers=headers(value), json={})
    assert result.status_code == 409 and "Фото" in result.text
    status["identity_enrolled"] = True
    assert (
        client.post(
            f"/api/student/{sid}/start", headers=headers(value), json={}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/student/{sid}/enroll", headers=headers(value), json={}
        ).status_code
        == 409
    )


def test_reference_photo_is_teacher_only_and_does_not_export_embedding(
    client, monkeypatch, tmp_path
):
    from backend.security import encrypt

    monkeypatch.setattr(module, "DATA", tmp_path)
    value = create(client)
    sid = value["session"]["id"]
    reference = tmp_path / "reference" / (sid + ".sg")
    reference.parent.mkdir()
    reference.write_bytes(
        encrypt(
            json.dumps(
                {
                    "photo": "data:image/jpeg;base64,fixture",
                    "embedding": [1, 0],
                    "model": "SFace",
                }
            ).encode(),
            module.media_key,
        )
    )
    result = client.get(f"/api/sessions/{sid}/reference")
    assert result.status_code == 200 and "embedding" not in result.json()
    client.post("/api/auth/logout")
    assert (
        client.get(f"/api/sessions/{sid}/reference", headers=headers(value)).status_code
        == 401
    )
    assert client.get("/api/camera/stream?ticket=invalid").status_code == 403


def test_strict_rejects_remote_session_even_with_other_guard_claims(client):
    value = create(client, mode="strict")
    sid = value["session"]["id"]
    guard = {
        "storage_enforced": True,
        "keyboard_enforced": True,
        "capture_protected": True,
        "application_enforced": True,
        "remote_enforced": True,
        "remote_session": True,
    }
    response = client.post(
        f"/api/student/{sid}/start",
        headers=headers(value),
        json={"guard": guard, "desktop": {"displays": 1}},
    )
    assert response.status_code == 409 and "Қашықтан" in response.text


def test_launch_replay_and_platform_binding(client):
    key = "k" * 40
    module.store.set_setting("moodle_key", key)
    payload = {
        "exp": time.time() + 60,
        "nonce": "single-use",
        "userid": "42",
        "quizid": "17",
        "url": "https://localhost/mod/quiz/view.php?id=100",
    }
    value = create(client, launch_token=sign_launch(payload, key))
    assert (
        value["session"]["data"]["student"] == "42"
        and value["session"]["data"]["platform"] == "moodle"
    )
    module.engine.stop_camera()
    result = client.post(
        "/api/sessions",
        headers={"x-sergek-desktop": "test-desktop-key"},
        json={
            "student": "Other",
            "exam": "Other",
            "consent": True,
            "launch_token": sign_launch(payload, key),
        },
    )
    assert result.status_code == 409


def test_external_exam_requires_teacher_exit(client):
    value = create(client, platform="platonus")
    sid = value["session"]["id"]
    h = headers(value)
    assert (
        client.post(f"/api/student/{sid}/start", headers=h, json={}).status_code == 200
    )
    assert (
        client.post(f"/api/student/{sid}/finish", headers=h, json={}).status_code == 403
    )
    assert (
        client.post(
            f"/api/student/{sid}/finish",
            headers=h,
            json={"password": "StrongTeacher123!"},
        ).status_code
        == 200
    )


def test_hub_auth_and_chain_validation(client):
    module.store.set_setting("hub_receive_key", "h" * 40)
    packet = {
        "packet_id": "b" * 32,
        "sent_at": time.time(),
        "session": {
            "id": "a" * 32,
            "created": "2026-10-06T00:00:00+00:00",
            "ended": None,
            "status": "active",
            "data": {"student": "Remote", "exam": "Exam", "platform": "moodle"},
        },
        "events": [],
        "evidence": {},
    }
    raw = canonical(packet)
    assert client.post("/api/hub/ingest", content=raw).status_code == 403
    signature = hmac.new(("h" * 40).encode(), raw, hashlib.sha256).hexdigest()
    assert (
        client.post(
            "/api/hub/ingest", content=raw, headers={"x-sergek-signature": signature}
        ).status_code
        == 200
    )
    assert module.store.session("a" * 32)["data"]["remote"] is True
    assert (
        client.post(
            "/api/hub/ingest", content=raw, headers={"x-sergek-signature": signature}
        ).status_code
        == 409
    )
    assert client.post("/api/sessions/" + "a" * 32 + "/stop").status_code == 200
    packet["packet_id"] = "c" * 32
    raw = canonical(packet)
    signature = hmac.new(("h" * 40).encode(), raw, hashlib.sha256).hexdigest()
    assert (
        client.post(
            "/api/hub/ingest", content=raw, headers={"x-sergek-signature": signature}
        ).json()["stop"]
        is True
    )


def test_student_cannot_weaken_protection_or_forge_native_start(client):
    p = client.get("/api/profile").json()
    p["exam_mode"] = "strict"
    client.put("/api/profile", json=p)
    value = create(client)  # Helper supplies mode=monitor; profile remains strict.
    assert value["session"]["data"]["mode"] == "strict"
    sid = value["session"]["id"]
    assert client.post(f"/api/student/{sid}/start", json={},
                       headers={"Authorization": "Bearer " + value["token"]}).status_code == 403


def test_microphone_is_required_and_loss_interrupts_exam(client, monkeypatch):
    p = client.get("/api/profile").json()
    p["policy"]["microphone_required"] = True
    client.put("/api/profile", json=p)
    value = create(client)
    sid = value["session"]["id"]
    status = {"microphone_running": False, "microphone_error": "Микрофон өшірілген"}
    monkeypatch.setattr(module.engine, "status", lambda: status)
    assert client.post(f"/api/student/{sid}/start", headers=headers(value), json={}).status_code == 409
    status.update(microphone_running=True, microphone_error="")
    assert client.post(f"/api/student/{sid}/start", headers=headers(value), json={}).status_code == 200
    status["microphone_running"] = False
    result = client.post(f"/api/student/{sid}/heartbeat", headers=headers(value), json={})
    assert result.json()["status"] == "interrupted"
    assert module.engine.sid is None


def test_guard_interruption_preserves_reason_and_is_idempotent(client):
    value = create(client, mode="monitor")
    sid = value["session"]["id"]
    data = {"sid": sid, "reason": "application_close_failed"}
    desktop_headers = {"x-sergek-desktop": "test-desktop-key"}
    for _ in range(2):
        assert client.post("/api/desktop/interrupt", json=data, headers=desktop_headers).status_code == 200
    session = module.store.session(sid)
    assert session["status"] == "interrupted"
    assert session["data"]["interruption_reason"] == "application_close_failed"
    assert len([e for e in module.store.events(sid) if e["kind"] == "session_interrupted"]) == 1
    assert module.engine.sid is None


def test_blocked_background_resource_goes_to_audit_without_student_event(client):
    value=create(client,mode="monitor");sid=value["session"]["id"]
    data={"action":"resource_blocked","detail":{"sid":sid,"host":"cdn.jsdelivr.net","resource_type":"script"}}
    assert client.post('/api/desktop/audit',json=data).status_code==403
    response=client.post('/api/desktop/audit',json=data,headers={'x-sergek-desktop':'test-desktop-key'})
    assert response.status_code==200
    assert not module.store.events(sid)
    action,raw=module.store.db.execute('select action,detail from audit order by id desc limit 1').fetchone()
    assert action=='resource_blocked' and json.loads(raw)['blocked'] is True


def test_previous_two_second_audio_profile_migrates_without_crashing(client):
    p=module.store.setting('profile',module.Profile().model_dump())
    p['policy']['sound_seconds']=2;module.store.set_setting('profile',p)
    assert client.get('/api/profile').json()['policy']['sound_seconds']==4


def test_moodle_preflight_cancel_needs_no_teacher_password(client):
    value = create(client, platform="moodle")
    assert client.post(f"/api/student/{value['session']['id']}/finish",
                       headers=headers(value), json={}).status_code == 200


def test_only_moodle_server_can_finish_matching_signed_exam(client):
    key = "m" * 40
    module.store.set_setting("moodle_key", key)
    payload = {"exp": time.time()+60, "nonce": "submitted-once", "userid": "42", "quizid": "17",
               "student_name": "Мейірбек Бердібек", "exam_name": "Бағдарламалау",
               "url": "https://localhost/mod/quiz/view.php?id=100", "mode": "monitor"}
    value = create(client, launch_token=sign_launch(payload, key))
    sid = value["session"]["id"]
    assert value["session"]["data"]["student"] == payload["student_name"]
    assert client.post(f"/api/student/{sid}/start", headers=headers(value), json={}).status_code == 200
    body = {"nonce": payload["nonce"], "userid": "42", "quizid": "17", "attemptid": "1"}
    assert client.post("/api/moodle/finish", json=body).status_code == 403
    assert client.post("/api/moodle/finish", json={**body, "userid": "43"},
                       headers={"x-sergek-moodle": key}).status_code == 404
    assert module.store.session(sid)["status"] == "active"
    assert client.post("/api/moodle/finish", json=body, headers={"x-sergek-moodle": key}).status_code == 200
    assert module.store.session(sid)["status"] == "completed"
    assert module.engine.sid is None
    assert client.post("/api/moodle/finish", json=body, headers={"x-sergek-moodle": key}).json()["status"] == "completed"


def test_moodle_start_waits_for_matching_active_hub_session(client, monkeypatch):
    key = 'm' * 40
    module.store.set_setting('moodle_key', key)
    module.store.set_setting('hub', {'enabled': True, 'url': 'https://localhost:9443', 'pairing_key': 'h'*40})
    token = sign_launch({'exp': time.time()+60, 'nonce': 'ready-once', 'userid': '42', 'quizid': '17',
                        'url': 'https://localhost/mod/quiz/view.php?id=100', 'mode': 'monitor'}, key)
    value = create(client, launch_token=token); sid = value['session']['id']
    legacy=module.store.session(sid)['data']['policy']
    legacy.update(camera_required=True,liveness_required=True)
    module.store.update_session(sid,patch={'policy':legacy})
    camera={'models_ready':True,'camera_running':True,'identity_enrolled':False}
    monkeypatch.setattr(module.engine,'status',lambda:camera)
    route = f'/api/student/{sid}/moodle-ready'
    assert client.post(route,headers=headers(value),json={}).status_code==409
    camera['identity_enrolled']=True
    sent = []
    monkeypatch.setattr(module, 'sync_hub', lambda ids, **kw: sent.append(ids))
    state = {'active': False, 'prepared': False, 'session_id': sid, 'mode': 'monitor'}
    def answer(url, **kw):
        assert url == 'https://localhost:9443/api/moodle/status'
        assert kw['params']['nonce'] == 'ready-once'
        assert kw['headers']['x-sergek-moodle'] == key
        return httpx.Response(200, json=state, request=httpx.Request('GET', url))
    monkeypatch.setattr(module, 'local_request', lambda method,url,**kw:answer(url,**kw))
    assert client.post(route, headers=headers(value), json={}).json()['ready'] is False
    state['prepared'] = True
    assert client.post(route, headers=headers(value), json={}).json()['ready'] is True
    assert module.store.session(sid)['started'] is None
    assert client.post(f'/api/student/{sid}/start', headers=headers(value), json={}).status_code == 200
    assert client.post(route, headers=headers(value), json={}).json()['ready'] is False
    state.update(active=True, session_id='other-session')
    assert client.post(route, headers=headers(value), json={}).json()['ready'] is False
    state.update(session_id=sid, mode='strict')
    assert client.post(route, headers=headers(value), json={}).json()['ready'] is False
    state.update(mode='monitor')
    assert client.post(route, headers=headers(value), json={}).json()['ready'] is True
    assert sent == [[sid]] * 6
    assert client.post(route, json={}).status_code == 401
    monkeypatch.setattr(module, 'local_request', lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError('offline')))
    result = client.post(route, headers=headers(value), json={})
    assert result.status_code == 200 and not result.json()['ready']
    assert 'хабына байланыс жоқ' in result.json()['message']


def test_photo_starts_without_gestures_even_with_legacy_session_policy(client, monkeypatch):
    p=client.get('/api/profile').json();p['policy']['camera_required']=True
    client.put('/api/profile',json=p)
    monkeypatch.setattr(module.engine,'status',lambda:{'models_ready':True,'camera_running':True,'identity_enrolled':True})
    value=create(client);sid=value['session']['id']
    legacy=module.store.session(sid)['data']['policy'];legacy['liveness_required']=True
    module.store.update_session(sid,patch={'policy':legacy})
    r=client.post(f'/api/student/{sid}/start',headers=headers(value),json={})
    assert r.status_code==200
    assert r.json()['status']=='active' and r.json()['started']
    assert r.json()['data']['liveness_verified'] is False


def test_readiness_sync_does_not_wait_for_large_media_or_finish_poll(client, monkeypatch, tmp_path):
    value=create(client);sid=value['session']['id']
    module.store.update_session(sid,'active',{'platform':'moodle'})
    event=module.store.add_event(sid,'phone_detected',{})
    module.store.attach_media(event['id'],'large.sg')
    (tmp_path/'evidence').mkdir();(tmp_path/'evidence/large.sg').write_bytes(b'not decrypted on readiness')
    monkeypatch.setattr(module,'DATA',tmp_path)
    module.store.set_setting('hub',{'enabled':True,'url':'https://localhost:9443','pairing_key':'h'*40})
    def answer(url,**kwargs):
        packet=json.loads(kwargs['content'])
        assert not packet['evidence'] and packet['session']['status']=='active'
        assert kwargs['timeout']==2
        return httpx.Response(200,json={'ok':True},request=httpx.Request('POST',url))
    monkeypatch.setattr(module,'local_request',lambda method,url,**kw:answer(url,**kw))
    monkeypatch.setattr(module,'reconcile_moodle',lambda item:pytest.fail('Readiness must not wait for submission polling'))
    assert module.sync_hub([sid],control=True) is not False
    assert module.store.setting('synced_media:'+sid)==[]


def test_readiness_returns_when_background_upload_holds_the_lock(client, monkeypatch):
    value=create(client)
    class BusyLock:
        def acquire(self,timeout):
            assert timeout==2
            return False
        def release(self):
            pytest.fail('Unacquired lock cannot be released')
    monkeypatch.setattr(module,'hub_sync_lock',BusyLock())
    assert module.sync_hub([value['session']['id']],control=True) is False


def test_loopback_transport_preserves_https_hostname_and_verification(client, monkeypatch):
    trust=object();seen={}
    def transport(**kw):
        assert kw=={'verify':trust,'local_address':'127.0.0.1'}
        return 'transport'
    class FakeClient:
        def __init__(self,**kw):assert kw=={'transport':'transport','timeout':2}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def request(self,method,url,**kw):
            seen.update(method=method,url=url,kwargs=kw)
            return 'response'
    monkeypatch.setattr(module.httpx,'HTTPTransport',transport)
    monkeypatch.setattr(module.httpx,'Client',FakeClient)
    assert module.local_request('GET','https://localhost:9443/api/health',verify=trust,timeout=2,headers={'x-test':'value'})=='response'
    assert seen=={'method':'GET','url':'https://localhost:9443/api/health','kwargs':{'headers':{'x-test':'value'}}}


def test_university_server_keeps_normal_ipv4_ipv6_transport(client, monkeypatch):
    monkeypatch.setattr(module.httpx,'get',lambda url,**kw:(url,kw))
    result=module.local_request('GET','https://university.example/api/health',verify=True,timeout=2)
    assert result==('https://university.example/api/health',{'verify':True,'timeout':2})


def test_legacy_saved_profile_cannot_restore_manual_challenge(client):
    p=client.get('/api/profile').json();p['policy']['liveness_required']=True
    module.store.set_setting('profile',p)
    assert 'liveness_required' not in client.get('/api/profile').json()['policy']
    assert client.put('/api/profile',json=p).status_code==200
    value=create(client)
    assert 'liveness_required' not in value['session']['data']['policy']
    assert '/api/student/{sid}/liveness' not in module.app.openapi()['paths']
    assert client.post(f"/api/student/{value['session']['id']}/liveness",headers=headers(value),json={}).status_code==405


def test_lost_moodle_callback_only_finishes_exact_server_owned_attempt(client,monkeypatch):
    key='m'*40;module.store.set_setting('moodle_key',key)
    signed={'exp':time.time()+60,'nonce':'reconcile','userid':'42','quizid':'17',
        'url':'https://localhost/mod/quiz/view.php?id=100','mode':'monitor'}
    value=create(client,launch_token=sign_launch(signed,key));sid=value['session']['id']
    client.post(f'/api/student/{sid}/start',headers=headers(value),json={})
    result={**signed,'state':'finished','attemptid':10,'userid':'43'}
    def answer(url,**kw):
        assert url=='https://localhost/mod/quiz/accessrule/sergek/status.php'
        assert kw['headers']['X-Sergek-Moodle']==key
        return httpx.Response(200,json=result,request=httpx.Request('GET',url))
    monkeypatch.setattr(module,'local_request',lambda method,url,**kw:answer(url,**kw))
    module.reconcile_moodle(module.store.session(sid));assert module.store.session(sid)['status']=='active'
    result['userid']='42';module.reconcile_moodle(module.store.session(sid))
    assert module.store.session(sid)['status']=='completed' and module.store.session(sid)['ended']


def test_hub_never_rolls_active_session_back_to_prepared(client):
    key='h'*40;module.store.set_setting('hub_receive_key',key)
    item={'id':'e'*32,'created':'2026-10-07T00:00:00+00:00','started':None,'ended':None,'status':'active','data':{}}
    def send():
        packet={'packet_id':__import__('uuid').uuid4().hex,'sent_at':time.time(),'session':item,'events':[],'evidence':{}}
        raw=canonical(packet)
        return client.post('/api/hub/ingest',content=raw,headers={'x-sergek-signature':hmac.new(key.encode(),raw,hashlib.sha256).hexdigest()})
    assert send().status_code==200
    item['status']='preflight';assert send().status_code==409
    assert module.store.session(item['id'])['status']=='active'
