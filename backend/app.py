import os, time, secrets, hashlib, hmac, json, sqlite3, threading, base64, logging, ssl, uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import httpx
import asyncio
from fastapi import FastAPI, Request, HTTPException, Depends, Response
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from .config import (
    DATA,
    MODELS,
    ROOT,
    DESKTOP_KEY,
    Profile,
    SessionCreate,
    Login,
    Review,
    CalibrationPoint,
    AgentEvent,
    HubConfig,
)
from .store import Store, utc
from .security import (
    hash_password,
    verify_password,
    load_key,
    verify_launch,
    canonical,
    encrypt,
    decrypt,
)
from .engine import Engine
from .reports import payload, pdf_report
from .event_policy import annotate

store = Store(DATA / "sergek.db")
if os.environ.get("SERGEK_DEMO_CONFIG"):
    from .demo import bootstrap_demo
    bootstrap_demo(store, os.environ["SERGEK_DEMO_CONFIG"])
media_key = load_key(DATA / "media.key")
engine = Engine(store, MODELS, DATA, media_key)
teacher_tokens = {}
student_tokens = {}
camera_tickets = {}
login_attempts = {}
heartbeats = {}
maintenance_stop = threading.Event()
hub_sync_lock = threading.RLock()


def profile():
    saved = store.setting("profile", Profile().model_dump())
    if saved.get("policy", {}).get("sound_seconds", 4) < 3:
        saved["policy"]["sound_seconds"] = 4
    if saved.get('policy',{}).get('phone_confidence') == 0.4:
        saved['policy']['phone_confidence'] = 0.30
    return Profile.model_validate(saved)


def local_request(method, url, **kwargs):
    """Our lab binds IPv4 loopback; avoid Windows' 2s IPv6 fallback per request.

    The HTTPS URL, SNI and certificate verification remain unchanged. Other
    servers use their normal IPv4/IPv6 resolution.
    """
    if urlparse(url).hostname != 'localhost':
        return getattr(httpx, method.lower())(url, **kwargs)
    verify = kwargs.pop('verify', True)
    timeout = kwargs.pop('timeout', 5)
    transport = httpx.HTTPTransport(verify=verify, local_address='127.0.0.1')
    with httpx.Client(transport=transport, timeout=timeout) as client:
        return client.request(method, url, **kwargs)


def clean_session(item):
    if not item:
        return None
    result = json.loads(json.dumps(item))
    result["data"].pop("launch_token", None)
    return result


def is_loopback(request):
    return request.client and request.client.host in ("127.0.0.1", "::1", "testclient")


def desktop(request: Request):
    value = request.headers.get("x-sergek-desktop", "")
    if (
        not DESKTOP_KEY
        or not hmac.compare_digest(value, DESKTOP_KEY)
        or not is_loopback(request)
    ):
        raise HTTPException(403, "Desktop access required")


def teacher(request: Request):
    token = request.cookies.get("sergek_teacher", "")
    expiry = teacher_tokens.get(token, 0)
    if expiry < time.time():
        raise HTTPException(401, "Мұғалім ретінде кіріңіз")
    return token


def session_auth(request: Request, sid: str):
    value = request.headers.get("authorization", "").removeprefix("Bearer ")
    record = student_tokens.get(value)
    if not record or record["sid"] != sid or record["expires"] < time.time():
        raise HTTPException(401, "Invalid session access")
    return record


def allowed_exam(url, p):
    target = urlparse(url)
    try:
        return (
            target.scheme == "https"
            and target.hostname in p.allowed_hosts
            and target.port in (None, 443)
            and not target.username
            and not target.password
        )
    except ValueError:
        return False


def maintenance():
    while not maintenance_stop.wait(5):
        try:
            for sid, last in list(heartbeats.items()):
                item = store.session(sid)
                if item and item["status"] == "active" and time.monotonic() - last > 12:
                    store.add_event(
                        sid,
                        "guard_lost",
                        {
                            "message": "Desktop heartbeat lost; OS helper expires its restrictions separately."
                        },
                    )
                    store.update_session(sid, "interrupted")
                    heartbeats.pop(sid, None)
                    if engine.sid == sid:
                        engine.stop_camera()
            cutoff = datetime.now(timezone.utc) - timedelta(
                days=profile().policy.retention_days
            )
            for item in store.sessions():
                if (
                    item["status"] in ("completed", "interrupted")
                    and datetime.fromisoformat(item["created"]) < cutoff
                ):
                    delete_data(item["id"])
        except Exception:
            logging.exception("Maintenance failed")


def synchronize():
    while not maintenance_stop.wait(5):
        try:
            sync_hub()
        except Exception:
            logging.exception("Hub synchronization failed")


def delete_data(sid):
    (DATA / "reference" / (sid + ".sg")).unlink(missing_ok=True)
    for event in store.events(sid):
        if event["media"]:
            (DATA / "evidence" / event["media"]).unlink(missing_ok=True)
    store.delete_session(sid)


def sync_hub(sids=None, control=False):
    # Serialize each session packet, and read it inside the lock. A delayed
    # preflight packet must not overwrite the active packet acknowledged at start.
    # Prioritize the current exam, never resend every archived session forever.
    items = store.sessions() if sids is None else []
    items.sort(key=lambda s: s['status'] not in ('active', 'preflight'))
    # Bound archived uploads so a slow backlog cannot starve a live exam's 15s lease.
    live = [i['id'] for i in items if i['status'] in ('active','preflight') and not i['data'].get('remote')]
    archived = [i['id'] for i in items if i['status'] not in ('active','preflight') and not i['data'].get('remote')
                and store.setting('synced_revision:'+i['id']) != sync_revision(i,store.events(i['id']))]
    ids = sids if sids is not None else live if live else archived[:2]
    for sid in ids:
        acquired = hub_sync_lock.acquire(timeout=2 if control else -1)
        if not acquired:
            return False
        try:
            if _sync_hub([sid], control=control) is False:
                return False
        finally:
            hub_sync_lock.release()


def sync_revision(item, events):
    return hashlib.sha256(canonical({'status':item['status'], 'ended':item['ended'],
        'events':[(e['id'],e['media']) for e in events]})).hexdigest()


def _sync_hub(sids=None, control=False):
    config = store.setting("hub", {})
    if (
        not config.get("enabled")
        or not config.get("url")
        or not config.get("pairing_key")
    ):
        return
    for item in (
        [store.session(sid) for sid in sids] if sids else store.sessions()[:100]
    ):
        if not item:
            continue
        if item["data"].get("remote"):
            continue
        events = store.events(item["id"])
        revision = sync_revision(item, events)
        if item['status'] in ('completed','interrupted') and store.setting('synced_revision:'+item['id']) == revision:
            continue
        evidence = {}
        budget = 0 if control else 12_000_000
        acknowledged = set(store.setting("synced_media:" + item["id"], []))
        for event in events:
            if event["media"] and event["id"] not in acknowledged:
                path = DATA / "evidence" / event["media"]
                if path.exists() and path.stat().st_size <= budget:
                    evidence[event["id"]] = base64.b64encode(
                        decrypt(path.read_bytes(), media_key)
                    ).decode()
                    budget -= path.stat().st_size
        packet = {
            "packet_id": uuid.uuid4().hex,
            "sent_at": time.time(),
            "session": clean_session(item),
            "events": events,
            "evidence": evidence,
        }
        reference = DATA / "reference" / (item["id"] + ".sg")
        if reference.exists():
            saved = json.loads(decrypt(reference.read_bytes(), media_key))
            packet["reference"] = {
                k: v for k, v in saved.items() if k in ("photo", "enrolled_at", "model")
            }
        raw = canonical(packet)
        signature = hmac.new(
            config["pairing_key"].encode(), raw, hashlib.sha256
        ).hexdigest()
        try:
            trust = (
                ssl.create_default_context(cafile=os.environ["SERGEK_CA_FILE"])
                if os.environ.get("SERGEK_CA_FILE")
                else True
            )
            response = local_request("POST",
                config["url"].rstrip("/") + "/api/hub/ingest",
                content=raw,
                headers={
                    "x-sergek-signature": signature,
                    "Content-Type": "application/json",
                },
                timeout=2 if control else 8,
                verify=trust,
            )
            response.raise_for_status()
            store.set_setting("hub_status", {"ok": True, "last_sync": utc()})
            store.set_setting('synced_revision:'+item['id'], revision)
            store.set_setting(
                "synced_media:" + item["id"], list(acknowledged.union(evidence))
            )
            if response.json().get("stop") and item["status"] in (
                "active",
                "preflight",
            ):
                stop_reason = response.json().get("stop_reason", "teacher_stop")
                store.add_event(item["id"], stop_reason, {"source": "paired_hub"})
                store.update_session(item["id"], "completed")
                heartbeats.pop(item["id"], None)
                if engine.sid == item["id"]:
                    engine.stop_camera()
            elif not control and item['status'] == 'active' and item['data'].get('platform') == 'moodle':
                reconcile_moodle(item)
        except Exception as exc:
            store.set_setting(
                "hub_status", {"ok": False, "error": str(exc), "last_sync": utc()}
            )
            return False


def reconcile_moodle(item):
    """Recover a lost submission callback using Moodle's signed server-side state."""
    from urllib.parse import urlsplit, urlunsplit
    key = store.setting('moodle_key', '')
    signed = item['data'].get('moodle', {})
    if not key or not signed.get('nonce'):
        return
    target = urlsplit(item['data']['exam_url'])
    base = target.path.split('/mod/quiz/')[0]
    url = urlunsplit((target.scheme, target.netloc, base+'/mod/quiz/accessrule/sergek/status.php','',''))
    try:
        trust = ssl.create_default_context(cafile=os.environ['SERGEK_CA_FILE']) if os.environ.get('SERGEK_CA_FILE') else True
        response = local_request('GET',url, params={'nonce':signed['nonce']}, headers={'X-Sergek-Moodle':key}, verify=trust, timeout=3)
        response.raise_for_status()
        result = response.json()
        if (result.get('state') == 'finished' and all(str(result.get(k)) == str(signed.get(k)) for k in ('nonce','userid','quizid'))):
            store.update_session(item['id'], 'completed', {'stop_reason':'moodle_submitted', 'moodle_attempt':str(result['attemptid'])})
            store.audit('moodle_submission_reconciled', {'sid':item['id'],'attempt':str(result['attemptid'])})
            heartbeats.pop(item['id'], None)
            if engine.sid == item['id']:
                engine.stop_camera()
    except (httpx.HTTPError, ValueError, OSError):
        # A network failure must never be interpreted as a successful submission.
        return
    return True


@asynccontextmanager
async def lifespan(app):
    for item in store.sessions():
        if item["status"] in ("active", "preflight") and not item["data"].get("remote"):
            store.add_event(
                item["id"],
                "session_interrupted",
                {
                    "message": "Backend restarted; previous session was not silently resumed."
                },
            )
            store.update_session(item["id"], "interrupted")
    thread = threading.Thread(target=maintenance, daemon=True)
    thread.start()
    sync_thread = threading.Thread(target=synchronize, daemon=True)
    sync_thread.start()
    yield
    maintenance_stop.set()
    engine.stop_camera()
    if engine.vision:
        engine.vision.close()


APP_VERSION = os.environ.get("SERGEK_VERSION", "1.4.3")
app = FastAPI(
    title="Sergek Proctor",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)


@app.middleware("http")
async def protect(request, call_next):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        return JSONResponse(
            {"detail": "Cross-origin request rejected"}, status_code=403
        )
    if (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        and request.headers.get("sec-fetch-site") == "cross-site"
    ):
        return JSONResponse({"detail": "Cross-site request rejected"}, status_code=403)
    if (
        request.headers.get("content-length", "0").isdigit()
        and int(request.headers.get("content-length", "0")) > 30_000_000
    ):
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = (
        "no-store" if request.url.path.startswith("/api/") else "no-cache"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
    )
    return response


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": APP_VERSION,
        "setup_required": not bool(store.setting("password")),
    }


@app.get("/api/desktop/ping", dependencies=[Depends(desktop)])
def desktop_ping():
    return {"ok": True}


@app.post("/api/desktop/authorize", dependencies=[Depends(desktop)])
def authorize(value: Login):
    if not verify_password(value.password, store.setting("password", "")):
        raise HTTPException(403, "Мұғалім құпиясөзі қажет")
    return {"ok": True}


@app.post("/api/desktop/resolve-launch", dependencies=[Depends(desktop)])
def resolve_launch(value: dict):
    try:
        launch = verify_launch(
            str(value.get("token", "")), store.setting("moodle_key", "")
        )
        if not store.setting("moodle_key") or not allowed_exam(
            launch["url"], profile()
        ):
            raise ValueError("Moodle launch is not configured or URL is not allowed")
        return {
            "student": str(launch.get("student_name") or ("Moodle #" + str(launch["userid"])))[:120],
            "exam": str(launch.get("exam_name") or ("Moodle quiz #" + str(launch["quizid"])))[:160],
            "exam_url": launch["url"],
            "platform": "moodle",
            "mode": launch.get("mode", "strict"),
        }
    except Exception as exc:
        raise HTTPException(403, str(exc))


@app.post("/api/desktop/interrupt", dependencies=[Depends(desktop)])
def desktop_interrupt(value: dict):
    sid = value.get("sid")
    item = store.session(sid)
    if not item:
        raise HTTPException(404)
    if item["status"] in ("completed", "interrupted"):
        return {"ok": True}
    store.add_event(
        sid,
        "session_interrupted",
        {"reason": str(value.get("reason", "unknown"))[:160]},
    )
    heartbeats.pop(sid, None)
    store.update_session(sid, "interrupted", {"interruption_reason": str(value.get("reason", "unknown"))[:160]})
    if engine.sid == sid:
        try:
            engine.stop_camera()
        except Exception:
            logging.exception("Capture worker failed to stop")
    return {"ok": True}


@app.post("/api/desktop/audit", dependencies=[Depends(desktop)])
def desktop_audit(value: dict):
    action = value.get("action")
    if action not in {"resource_blocked", "navigation_blocked", "download_blocked", "window_blocked"}:
        raise HTTPException(422, "Unsupported desktop audit action")
    detail = value.get("detail", {})
    if not isinstance(detail, dict):
        raise HTTPException(422, "Audit detail must be an object")
    safe = {k: str(detail.get(k, ""))[:160] for k in ("sid", "host", "resource_type")}
    safe["blocked"] = True
    store.audit(action, safe)
    return {"ok": True}


@app.post("/api/setup", dependencies=[Depends(desktop)])
def setup(value: Login):
    if store.setting("password"):
        raise HTTPException(409, "Already configured")
    if len(value.password) < 12:
        raise HTTPException(422, "Құпиясөз кемінде 12 таңба болсын")
    store.set_setting("password", hash_password(value.password))
    store.audit("setup", {})
    return {"ok": True}


@app.post("/api/auth/login")
def login(value: Login, request: Request, response: Response):
    address = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = [t for t in login_attempts.get(address, []) if now - t < 60]
    if len(attempts) >= 5:
        raise HTTPException(429, "Бір минуттан кейін қайталаңыз")
    login_attempts[address] = attempts + [now]
    if not verify_password(value.password, store.setting("password", "")):
        raise HTTPException(401, "Құпиясөз қате")
    token = secrets.token_urlsafe(32)
    teacher_tokens[token] = now + 8 * 3600
    response.set_cookie(
        "sergek_teacher",
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=8 * 3600,
    )
    login_attempts[address] = []
    store.audit("teacher_login", {"address": address})
    return {"ok": True}


@app.post("/api/auth/logout", dependencies=[Depends(teacher)])
def logout(request: Request, response: Response):
    teacher_tokens.pop(request.cookies.get("sergek_teacher", ""), None)
    response.delete_cookie("sergek_teacher")
    return {"ok": True}


@app.get("/api/auth/me", dependencies=[Depends(teacher)])
def me():
    return {"role": "teacher"}


@app.get("/api/profile")
def get_profile():
    return profile().model_dump()


@app.put("/api/profile", dependencies=[Depends(teacher)])
def set_profile(value: Profile):
    if any(item["status"] == "active" for item in store.sessions()):
        raise HTTPException(409, "Active exam: finish before changing policy")
    for host in value.allowed_hosts:
        if not host or "/" in host or ":" in host or "*" in host:
            raise HTTPException(422, "Exact hostnames required")
    for host, pin in value.tls_pins.items():
        if (
            host not in value.allowed_hosts
            or len(pin) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in pin)
        ):
            raise HTTPException(
                422, "TLS pin requires an allowlisted host and SHA-256 fingerprint"
            )
    if not allowed_exam(value.moodle_url, value) or not allowed_exam(
        value.platonus_url, value
    ):
        raise HTTPException(422, "Platform URLs must be HTTPS and allowlisted")
    store.set_setting("profile", value.model_dump())
    store.audit("profile_changed", value.model_dump())
    return value


@app.get("/api/diagnostics", dependencies=[Depends(teacher)])
def diagnostics():
    return {
        "vision": engine.status(),
        "hub": store.setting("hub_status", {}),
        "sessions": len(store.sessions()),
    }


@app.post("/api/sessions", dependencies=[Depends(desktop)])
def create_session(value: SessionCreate):
    if not store.setting("password"):
        raise HTTPException(409, "Мұғалім құпиясөзін алдымен орнатыңыз")
    if not value.consent:
        raise HTTPException(422, "Бақылау шарттарын қабылдау қажет")
    if engine.sid:
        raise HTTPException(409, "Алдыңғы сессияны аяқтаңыз")
    data = value.model_dump()
    p = profile()
    # Protection is controlled by the university profile or a signed Moodle launch.
    # A student request cannot weaken it by supplying mode="monitor".
    data["mode"] = p.exam_mode
    nonce = ""
    if value.launch_token:
        key = store.setting("moodle_key", "")
        if not key:
            raise HTTPException(409, "Moodle integration key is not configured")
        try:
            launch = verify_launch(value.launch_token, key)
        except Exception as exc:
            raise HTTPException(403, str(exc))
        if not allowed_exam(launch["url"], p):
            raise HTTPException(403, "Launch URL not allowed")
        data.update(
            student=str(launch.get("student_name") or launch["userid"])[:120],
            exam=str(launch.get("exam_name") or launch["quizid"])[:160],
            exam_url=launch["url"],
            platform="moodle",
            moodle=launch,
        )
        if launch.get("mode"):
            if launch["mode"] not in ("strict", "monitor"):
                raise HTTPException(403, "Invalid signed mode")
            data["mode"] = launch["mode"]
        nonce = launch["nonce"]
    elif value.platform != "local":
        data["exam_url"] = value.exam_url or (
            p.moodle_url if value.platform == "moodle" else p.platonus_url
        )
        if not allowed_exam(data["exam_url"], p):
            raise HTTPException(403, "Тест мекенжайы рұқсат етілмеген")
    data.pop("launch_token", None)
    data["policy"] = p.policy.model_dump()
    data["consent_at"] = utc()
    try:
        item = store.create_session(data, nonce)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Launch token already used")
    token = secrets.token_urlsafe(32)
    student_tokens[token] = {"sid": item["id"], "expires": time.time() + 12 * 3600}
    engine.start_camera(item["id"], value.camera_index, p.policy)
    return {"session": clean_session(item), "token": token}


@app.get("/api/student/{sid}/snapshot", dependencies=[Depends(session_auth)])
def snapshot(sid: str):
    return {
        **engine.snapshot(include_preview=False),
        "session": clean_session(store.session(sid)),
        "event_count": sum(annotate(event)["requires_review"] for event in store.events(sid)),
    }


@app.post("/api/student/{sid}/microphone/retry", dependencies=[Depends(session_auth), Depends(desktop)])
def retry_microphone(sid: str):
    item = store.session(sid)
    if engine.sid != sid or not item or item["status"] != "preflight":
        raise HTTPException(409, "Микрофон емтиханға дайындық кезінде ғана қайта тексеріледі")
    return engine.retry_microphone()


@app.post("/api/student/{sid}/camera-ticket", dependencies=[Depends(session_auth)])
def camera_ticket(sid: str):
    if engine.sid != sid:
        raise HTTPException(409, "Camera session ended")
    now = time.time()
    for key, value in list(camera_tickets.items()):
        if value["expires"] < now or value["sid"] != engine.sid:
            camera_tickets.pop(key, None)
    ticket = secrets.token_urlsafe(32)
    camera_tickets[ticket] = {"sid": sid, "expires": now + 12 * 3600}
    return {"ticket": ticket}


@app.get("/api/camera/stream")
async def camera_stream(request: Request, ticket: str):
    access = camera_tickets.get(ticket)
    if not access or access["expires"] < time.time() or access["sid"] != engine.sid:
        raise HTTPException(403, "Camera stream access denied")

    async def frames():
        serial = -1
        while engine.sid == access["sid"] and access["expires"] > time.time():
            if await request.is_disconnected():
                break
            with engine.lock:
                latest, blob = engine.frame_serial, engine.preview
            if blob and latest != serial:
                serial = latest
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(
                    len(blob)
                ).encode() + b"\r\n\r\n" + blob + b"\r\n"
            await asyncio.sleep(0.025)

    return StreamingResponse(
        frames(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.post("/api/student/{sid}/enroll", dependencies=[Depends(session_auth)])
def enroll_identity(sid: str):
    item = store.session(sid)
    if not item or item["status"] != "preflight" or engine.sid != sid:
        raise HTTPException(409, "Photo reference is locked during exam")
    if not engine.vision or not engine.vision.ready:
        raise HTTPException(409, "Бет салыстыру моделі дайын емес")
    try:
        result = engine.enroll()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    store.audit("identity_enrolled", {"sid": sid, "model": "SFace"})
    return result


@app.post("/api/desktop/frame", dependencies=[Depends(desktop)])
def desktop_frame(value: dict):
    item = store.session(str(value.get("sid", "")))
    if not item or item["status"] != "active" or engine.sid != item["id"]:
        raise HTTPException(409, "No recording session")
    if not item["data"]["policy"].get("screen_recording", True):
        return {"disabled": True}
    if value.get("clear"):
        with engine.lock:
            engine.exam_surface = None
        return {"ok": True}
    try:
        blob = base64.b64decode(value["jpeg"], validate=True)
        bounds = {k: int(value["bounds"][k]) for k in ["x", "y", "width", "height"]}
        if (
            blob[:2] != b"\xff\xd8"
            or not 0 < bounds["width"] <= 8192
            or not 0 < bounds["height"] <= 8192
        ):
            raise ValueError("Invalid exam frame")
        engine.set_exam_surface(blob, bounds)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc))
    return {"ok": True}


@app.post("/api/student/{sid}/calibrate", dependencies=[Depends(session_auth)])
def calibrate(sid: str, value: CalibrationPoint):
    if engine.sid != sid or not engine.vision:
        raise HTTPException(409, "Camera is not ready")
    item = store.session(sid)
    if item["status"] != "preflight":
        raise HTTPException(409, "Calibration is locked during exam")
    try:
        result = engine.vision.capture_calibration(value.direction)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    store.update_session(sid, patch={"calibration": result})
    return result


@app.post("/api/student/{sid}/start", dependencies=[Depends(session_auth), Depends(desktop)])
def start(sid: str, value: dict):
    item = store.session(sid)
    if not item or item["status"] != "preflight":
        raise HTTPException(409, "Not in preflight")
    vision = engine.status()
    native = value.get("guard", {})
    desktop_state = value.get("desktop", {})
    errors = []
    policy = Profile(policy=item["data"]["policy"]).policy
    if policy.microphone_required and (
        not vision.get("microphone_running") or vision.get("microphone_error")
    ):
        errors.append(vision.get("microphone_error") or "Микрофонды қосып, оған рұқсат беріңіз")
    if policy.camera_required:
        if not vision["models_ready"]:
            errors.append("AI модельдері дайын емес")
        if (
            not vision["camera_running"]
            or engine.signals.get("faces") != 1
            or engine.signals.get("quality") != "good"
        ):
            errors.append("Камерада бір бет анық көрінуі қажет")
        if not vision.get("identity_enrolled"):
            errors.append("Фотоға түсіп, бастапқы бетті тіркеңіз")
    strict = item["data"]["mode"] == "strict"
    if strict:
        if policy.usb_block and not native.get("storage_ready"):
            errors.append("USB қорғанысы дайын емес: жүйелік шектеу немесе құрылғыны тексеру орындалмады")
        if policy.keyboard_block and not native.get("keyboard_enforced"):
            errors.append("Windows перне қорғанысы іске қосылмады")
        if policy.keyboard_block and not native.get("capture_protected"):
            errors.append("Windows экранды түсіру қорғанысы расталмады")
        if policy.single_monitor and desktop_state.get("displays", 0) != 1:
            errors.append("Бір монитор ғана рұқсат етілген")
        if native.get("forbidden_processes"):
            errors.append("Бөгде бағдарламаларды автоматты жабу аяқталмады")
        if native.get('unapproved_applications'):
            errors.append('Бөгде бағдарламалардың автоматты жабылуын күтіңіз')
        if policy.close_applications and not native.get("application_enforced"):
            errors.append("Бағдарламаларды автоматты жабу қорғанысы қосылмады")
        if policy.remote_block and (
            native.get("remote_session") or not native.get("remote_enforced")
        ):
            errors.append("Қашықтан басқаруды бұғаттау расталмады")
    if errors:
        raise HTTPException(409, {"errors": errors})
    try:
        engine.start_recording()
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    store.update_session(
        sid,
        "active",
        {
            "active_started_at": utc(),
            "liveness_verified": False,
            "preflight": {
                "vision": vision,
                "guard": native,
                "desktop": desktop_state,
                "limitations": (
                    [] if strict else ["Monitor mode: OS blocking is not active"]
                ),
            },
        },
    )
    heartbeats[sid] = time.monotonic()
    return clean_session(store.session(sid))


@app.post("/api/student/{sid}/heartbeat", dependencies=[Depends(session_auth)])
def heartbeat(sid: str, value: dict):
    item = store.session(sid)
    if item and item["status"] == "active":
        state = engine.status()
        policy = item["data"]["policy"]
        reason = ""
        if policy.get("screen_recording") and state.get("screen_error"):
            reason = "screen_capture_error"
        if policy.get("microphone_required") and (
            state.get("microphone_error") or not state.get("microphone_running")
        ):
            reason = "microphone_disconnected"
        if state.get("evidence_error"):
            reason = "evidence_storage_failed"
        if policy.get("camera_required") and (state.get("last_frame_age", 0) or 0) > 5:
            reason = "camera_stalled"
        if (
            policy.get("camera_required")
            and (state.get("last_analysis_age", 0) or 0) > 8
        ):
            reason = "inference_stalled"
        if reason:
            store.add_event(sid, "session_interrupted", {"reason": reason})
            store.update_session(sid, "interrupted")
            heartbeats.pop(sid, None)
            try:
                engine.stop_camera()
            except Exception:
                logging.exception("Capture cleanup failed")
            return {"status": "interrupted"}
        heartbeats[sid] = time.monotonic()
    return {"status": item["status"] if item else "missing"}


@app.post("/api/student/{sid}/moodle-ready", dependencies=[Depends(session_auth), Depends(desktop)])
def moodle_ready(sid: str):
    item = store.session(sid)
    if not item or item['status'] not in ('preflight','active') or item['data'].get('platform') != 'moodle':
        raise HTTPException(409, 'Белсенді Moodle емтиханы қажет')
    if item['status'] == 'preflight':
        if item['data']['policy'].get('camera_required') and not engine.status().get('identity_enrolled'):
            raise HTTPException(409, 'Фотоға түсіңіз')
        store.update_session(sid, patch={'moodle_prepared':True})
    config = store.setting('hub', {})
    key = store.setting('moodle_key', '')
    nonce = item['data'].get('moodle', {}).get('nonce')
    if not config.get('enabled') or not config.get('url') or not key or not nonce:
        raise HTTPException(409, 'Moodle мен Sergек хабының байланысын әкімші баптауы қажет')
    synced = sync_hub([sid], control=True)
    if synced is False:
        return {'ready': False, 'message': 'Moodle байланысы қалпына келуде'}
    try:
        trust = ssl.create_default_context(cafile=os.environ['SERGEK_CA_FILE']) if os.environ.get('SERGEK_CA_FILE') else True
        response = local_request('GET',config['url'].rstrip('/') + '/api/moodle/status',
            params={'nonce': nonce}, headers={'x-sergek-moodle': key}, verify=trust, timeout=2)
        response.raise_for_status()
        state = response.json()
        ready = ((state.get('active') if item['status']=='active' else state.get('prepared')) is True and state.get('session_id') == sid
                 and state.get('mode') == item['data']['mode'])
        return {'ready': ready, 'message': '' if ready else 'Moodle қорғаныс сессиясын растауды күтіп тұр'}
    except (httpx.HTTPError, ValueError, OSError):
        return {'ready': False, 'message': 'Sergек хабына байланыс жоқ. Локалды таныстыру ортасын қайта іске қосыңыз'}


@app.post("/api/student/{sid}/event", dependencies=[Depends(session_auth)])
def agent_event(sid: str, value: AgentEvent):
    if engine.sid != sid:
        raise HTTPException(409, "Session not on this agent")
    return engine.record(value.kind, value.detail) or {"deduplicated": True}


@app.post("/api/student/{sid}/finish", dependencies=[Depends(session_auth)])
def finish(sid: str, value: dict):
    item = store.session(sid)
    if not item:
        raise HTTPException(404)
    if item["status"] in ("completed", "interrupted"):
        return clean_session(item)
    # Student can finish local exam; external exam exit requires teacher credential in desktop.
    if item["status"] == "active" and item["data"]["platform"] != "local" and not verify_password(
        str(value.get("password", "")), store.setting("password", "")
    ):
        raise HTTPException(403, "Сыртқы емтиханнан шығуды мұғалім растауы қажет")
    engine.stop_camera()
    heartbeats.pop(sid, None)
    item = store.update_session(sid, "completed", {"finished_at": utc()})
    sync_hub([sid])
    return clean_session(item)


QUESTIONS = [
    {
        "id": "1",
        "text": "Python тіліндегі өзгермейтін құрылым қайсы?",
        "choices": ["list", "tuple", "dict", "set"],
    },
    {
        "id": "2",
        "text": "HTTP 200 коды нені білдіреді?",
        "choices": ["Сәтті сұрау", "Табылмады", "Рұқсат жоқ", "Сервер қатесі"],
    },
    {
        "id": "3",
        "text": "SQLite деректерін сақтау үшін не қажет?",
        "choices": ["Бұлт сервері", "Локалды файл", "GPU", "Электрондық пошта"],
    },
    {
        "id": "4",
        "text": "ONNX моделін локалды орындауға не қолданылады?",
        "choices": ["Word", "ONNX Runtime", "SMTP", "Git log"],
    },
    {
        "id": "5",
        "text": "Прокторинг оқиғасы нені білдіреді?",
        "choices": [
            "Автоматты кінә",
            "Мұғалім тексеретін бақылау",
            "Міндетті нөл балл",
            "Баға журналы",
        ],
    },
]


@app.get("/api/student/{sid}/exam", dependencies=[Depends(session_auth)])
def local_exam(sid: str):
    item = store.session(sid)
    if item["data"]["platform"] != "local":
        raise HTTPException(404)
    return {
        "questions": QUESTIONS,
        "answers": store.answers(sid),
        "duration_seconds": 1800,
    }


@app.put("/api/student/{sid}/answer", dependencies=[Depends(session_auth)])
def answer(sid: str, value: dict):
    item = store.session(sid)
    if item["status"] != "active" or item["data"]["platform"] != "local":
        raise HTTPException(409, "Not active local exam")
    if value.get("question_id") not in [q["id"] for q in QUESTIONS] or value.get(
        "answer"
    ) not in range(4):
        raise HTTPException(422)
    store.save_answer(sid, value["question_id"], value["answer"])
    return {"saved_at": utc()}


@app.get("/api/sessions", dependencies=[Depends(teacher)])
def list_sessions():
    return [
        {**clean_session(s), "event_count": sum(annotate(e)["requires_review"] for e in store.events(s["id"])),
         "journal_count": len(store.events(s["id"]))}
        for s in store.sessions()
    ]


@app.get("/api/sessions/{sid}", dependencies=[Depends(teacher)])
def session_detail(sid: str):
    if not store.session(sid):
        raise HTTPException(404)
    return payload(store, sid)


@app.post("/api/sessions/{sid}/stop", dependencies=[Depends(teacher)])
def stop_session(sid: str):
    item = store.session(sid)
    if not item:
        raise HTTPException(404)
    if item["data"].get("remote"):
        store.update_session(sid, patch={"stop_requested": True})
        return {"requested": True}
    if engine.sid == sid:
        engine.stop_camera()
    heartbeats.pop(sid, None)
    store.audit("teacher_stop", {"sid": sid})
    return clean_session(store.update_session(sid, "completed"))


@app.get("/api/sessions/{sid}/reference", dependencies=[Depends(teacher)])
def reference_photo(sid: str):
    if not store.session(sid):
        raise HTTPException(404)
    path = DATA / "reference" / (sid + ".sg")
    if not path.exists():
        raise HTTPException(404, "No reference photo")
    saved = json.loads(decrypt(path.read_bytes(), media_key))
    return {k: v for k, v in saved.items() if k in ("photo", "enrolled_at", "model")}


@app.patch("/api/events/{eid}", dependencies=[Depends(teacher)])
def review_event(eid: str, value: Review):
    if not store.event(eid):
        raise HTTPException(404)
    return store.review(eid, value.verdict, value.note)


@app.get("/api/events/{eid}/evidence", dependencies=[Depends(teacher)])
def evidence(eid: str):
    item = store.event(eid)
    if not item or not item["media"]:
        raise HTTPException(404, "Evidence not yet available")
    store.audit("evidence_viewed", {"event_id": eid})
    return engine.evidence(item)


@app.get("/api/sessions/{sid}/report/{format}", dependencies=[Depends(teacher)])
def report(sid: str, format: str, lang: Literal["kk", "ru", "en"] = "kk"):
    if not store.session(sid):
        raise HTTPException(404)
    if format == "json":
        return Response(
            json.dumps(payload(store, sid), ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=sergek-{sid}.json"},
        )
    if format == "pdf":
        return Response(
            pdf_report(store, sid, lang),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=sergek-{sid}.pdf"},
        )
    raise HTTPException(404)


@app.delete("/api/sessions/{sid}", dependencies=[Depends(teacher)])
def delete_session(sid: str):
    item = store.session(sid)
    if not item:
        raise HTTPException(404)
    if item["status"] in ("active", "preflight"):
        raise HTTPException(409, "Finish the session first")
    delete_data(sid)
    return {"ok": True}


@app.get("/api/integration", dependencies=[Depends(teacher)])
def integration():
    return {
        "moodle_configured": bool(store.setting("moodle_key")),
        "hub_configured": bool(store.setting("hub_receive_key")),
        "hub": {
            k: v for k, v in store.setting("hub", {}).items() if k != "pairing_key"
        },
        "status": store.setting("hub_status", {}),
    }


@app.post("/api/integration/rotate-key", dependencies=[Depends(teacher)])
def rotate_key(value: dict):
    kind = value.get("kind")
    if kind not in ("moodle_key", "hub_receive_key"):
        raise HTTPException(422)
    key = secrets.token_urlsafe(40)
    store.set_setting(kind, key)
    store.audit("integration_key_rotated", {"kind": kind})
    return {"key": key}


@app.put("/api/integration/hub", dependencies=[Depends(teacher)])
def configure_hub(value: HubConfig):
    parsed = urlparse(value.url)
    if value.enabled and (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise HTTPException(422, "LAN hub requires HTTPS URL")
    if value.enabled and len(value.pairing_key) < 32:
        raise HTTPException(422, "Pairing key required")
    store.set_setting("hub", value.model_dump())
    return {"ok": True}


@app.put("/api/integration/moodle", dependencies=[Depends(teacher)])
def configure_moodle(value: dict):
    key = value.get("key", "")
    if not isinstance(key, str) or len(key) < 32 or len(key) > 256:
        raise HTTPException(422, "Integration key must have 32–256 characters")
    store.set_setting("moodle_key", key)
    store.audit("moodle_key_imported", {})
    return {"ok": True}


@app.post("/api/hub/ingest")
async def ingest(request: Request):
    key = store.setting("hub_receive_key", "")
    raw = await request.body()
    signature = request.headers.get("x-sergek-signature", "")
    if not key or not hmac.compare_digest(
        signature, hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
    ):
        raise HTTPException(403)
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(ingest_packet, raw)


def ingest_packet(raw):
    # Packet validation and stop-state merge share one lock with teacher commands.
    # Offload filesystem/SQLite work so concurrent heartbeat requests stay responsive.
    with store.lock:
        try:
            return _ingest_packet(raw)
        except Exception:
            store.db.rollback()
            raise


def _ingest_packet(raw):
    try:
        packet = json.loads(raw)
        packet_id = packet["packet_id"]
        sent_at = float(packet["sent_at"])
        item = packet["session"]
        sid = item["id"]
        if (
            len(packet_id) != 32
            or any(c not in "0123456789abcdef" for c in packet_id)
            or abs(time.time() - sent_at) > 30
        ):
            raise ValueError("Expired or invalid packet")
        if item["status"] not in (
            "preflight",
            "active",
            "completed",
            "interrupted",
        ) or not isinstance(item["data"], dict):
            raise ValueError("Invalid session")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc))
    with store.lock:
        try:
            store.db.execute(
                "INSERT INTO received_packets VALUES(?,?)", (packet_id, time.time())
            )
            store.db.execute(
                "DELETE FROM received_packets WHERE received<?", (time.time() - 3600,)
            )
            store.db.commit()
        except sqlite3.IntegrityError:
            store.db.rollback()
            raise HTTPException(409, "Packet replay rejected")
    if len(sid) != 32 or not all(c in "0123456789abcdef" for c in sid):
        raise HTTPException(422)
    current = store.session(sid)
    if current and not current["data"].get("remote"):
        raise HTTPException(409, "Local session conflict")
    if (
        current
        and current["status"] in ("completed", "interrupted")
        and item["status"] in ("active", "preflight")
    ):
        raise HTTPException(409, "Terminal session cannot become active again")
    if current and sent_at < current['data'].get('remote_sent_at', 0):
        raise HTTPException(409, "Out-of-order packet rejected")
    if current and current['status']=='active' and item['status']=='preflight':
        raise HTTPException(409, "Active session cannot return to preparation")
    item['data']['remote_sent_at'] = sent_at
    item["data"]["remote"] = True
    item["data"]["remote_last_seen"] = utc()
    if (
        current
        and current["data"].get("stop_requested")
        and item["status"] in ("active", "preflight")
    ):
        return {"stop": True, "stop_reason": current["data"].get("stop_reason", "teacher_stop")}
    events = packet.get("events", [])
    previous = "0" * 64
    for event in events:
        if len(event.get("id", "")) != 32 or not all(
            c in "0123456789abcdef" for c in event["id"]
        ):
            raise HTTPException(422, "Invalid event ID")
        expected = hashlib.sha256(
            canonical(
                {
                    k: event[k]
                    for k in [
                        "id",
                        "session_id",
                        "created",
                        "kind",
                        "detail",
                        "previous_hash",
                    ]
                }
            )
        ).hexdigest()
        if (
            event["session_id"] != sid
            or event["previous_hash"] != previous
            or event["hash"] != expected
        ):
            raise HTTPException(422, "Invalid event chain")
        previous = event["hash"]
    reference = packet.get("reference")
    if reference:
        photo = reference.get("photo", "")
        try:
            decoded = base64.b64decode(photo.split(",", 1)[1], validate=True)
            if (
                not photo.startswith("data:image/jpeg;base64,")
                or len(decoded) > 2_000_000
                or decoded[:2] != b"\xff\xd8"
            ):
                raise ValueError("Invalid reference photo")
        except (ValueError, IndexError):
            raise HTTPException(422, "Invalid reference photo")
        path = DATA / "reference" / (sid + ".sg")
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(
            encrypt(
                json.dumps(
                    {
                        k: v
                        for k, v in reference.items()
                        if k in ("photo", "enrolled_at", "model")
                    }
                ).encode(),
                media_key,
            )
        )
    with store.lock:
        store.db.execute(
            "INSERT OR REPLACE INTO sessions(id,created,ended,status,data,started) VALUES(?,?,?,?,?,?)",
            (
                sid,
                item["created"],
                item["ended"],
                item["status"],
                json.dumps(item["data"], ensure_ascii=False),
                item.get('started') or item['data'].get('active_started_at'),
            ),
        )
        for event in events:
            old = store.event(event["id"])
            verdict = old["verdict"] if old else "pending"
            note = old["note"] if old else ""
            media = old["media"] if old else None
            if event["id"] in packet.get("evidence", {}):
                media = event["id"] + ".sg"
                path = DATA / "evidence" / media
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(
                    encrypt(
                        base64.b64decode(packet["evidence"][event["id"]]), media_key
                    )
                )
            store.db.execute(
                "INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    event["id"],
                    sid,
                    event["created"],
                    event["kind"],
                    json.dumps(event["detail"], ensure_ascii=False),
                    event["previous_hash"],
                    event["hash"],
                    media,
                    verdict,
                    note,
                ),
            )
        store.db.commit()
    return {"ok": True, "stop": False}


@app.post("/api/moodle/finish")
def moodle_finish(value: dict, request: Request):
    key = store.setting("moodle_key", "")
    if not key or not hmac.compare_digest(request.headers.get("x-sergek-moodle", ""), key):
        raise HTTPException(403)
    matching = store.session_by_nonce(str(value.get('nonce','')))
    for item in ([matching] if matching else []):
        signed = item["data"].get("moodle", {})
        if signed.get("nonce") == value.get("nonce") and all(
            str(signed.get(k)) == str(value.get(k)) for k in ("userid", "quizid")
        ):
            if item["status"] != "active":
                return {"ok": True, "status": item["status"]}
            store.update_session(item["id"], patch={
                "stop_requested": True, "stop_reason": "moodle_submitted",
                "moodle_attempt": str(value.get("attemptid", ""))[:32],
            })
            store.audit("moodle_submitted", {"sid": item["id"]})
            if not item["data"].get("remote"):
                if engine.sid == item["id"]:
                    engine.stop_camera()
                heartbeats.pop(item["id"], None)
                store.update_session(item["id"], "completed", {"finished_at": utc()})
            return {"ok": True, "status": "finishing"}
    raise HTTPException(404, "Matching Moodle session not found")


@app.get("/api/moodle/status")
def moodle_status(nonce: str, request: Request):
    key = store.setting("moodle_key", "")
    if not key or not hmac.compare_digest(
        request.headers.get("x-sergek-moodle", ""), key
    ):
        raise HTTPException(403)
    item = store.session_by_nonce(nonce)
    if item:
            fresh = (
                not item["data"].get("remote")
                or (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(
                        item["data"].get("remote_last_seen", item["created"])
                    )
                ).total_seconds()
                < 15
            )
            return {
                "active": item["status"] == "active" and fresh and not item["data"].get("stop_requested"),
                "prepared": item['status'] == 'preflight' and fresh and bool(item['data'].get('moodle_prepared')),
                "session_id": item["id"],
                "status": item["status"],
                "mode": item["data"].get("mode"),
            }
    return {"active": False, "status": "not_started"}


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    folder = Path(os.environ.get("SERGEK_UI", str(ROOT / "dist"))).resolve()
    file = (folder / path).resolve()
    if not file.is_relative_to(folder):
        raise HTTPException(404)
    if file.is_file():
        return FileResponse(file)
    if (folder / "index.html").exists():
        return FileResponse(folder / "index.html")
    return Response("Build the UI first: npm run build", status_code=503)
