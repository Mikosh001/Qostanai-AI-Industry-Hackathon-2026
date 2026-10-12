"""Adversarial API regressions; isolated databases, no camera/OS restrictions."""

import copy
import hashlib
import hmac
import math
import time
import uuid
import asyncio
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest
from hypothesis import given, settings, strategies as st
from fastapi import HTTPException

from test_api import client, module
from backend.security import canonical, sign_launch, verify_launch
from backend.request_limits import RequestBodyLimit
from backend.security import encrypt, decrypt
from cryptography.exceptions import InvalidTag

KEY = "h" * 40


def packet(sid="a" * 32):
    return {
        "packet_id": uuid.uuid4().hex,
        "sent_at": time.time(),
        "session": {
            "id": sid,
            "created": "2026-10-06T00:00:00+00:00",
            "ended": None,
            "status": "active",
            "data": {"student": "Fixture"},
        },
        "events": [],
        "evidence": {},
    }


def event(sid, eid=None, previous="0" * 64, detail=None):
    value = {
        "id": eid or uuid.uuid4().hex,
        "session_id": sid,
        "created": "2026-10-06T00:00:00+00:00",
        "kind": "phone_detected",
        "detail": detail or {"confidence": 0.9},
        "previous_hash": previous,
    }
    value["hash"] = hashlib.sha256(canonical(value)).hexdigest()
    return value


def send(client, value):
    module.store.set_setting("hub_receive_key", KEY)
    raw = canonical(value)
    return client.post(
        "/api/hub/ingest",
        content=raw,
        headers={
            "x-sergek-signature": hmac.new(
                KEY.encode(), raw, hashlib.sha256
            ).hexdigest()
        },
    )


@pytest.mark.parametrize(
    "url", ["https://[", "https://]", "https://[::1", "https://localhost:bad"]
)
def test_malformed_exam_url_is_validation_error(client, url):
    p = client.get("/api/profile").json()
    p["moodle_url"] = url
    assert client.put("/api/profile", json=p).status_code == 422


@pytest.mark.parametrize(
    "origin",
    ["https://[", "null", "https://evil.example", "https://testserver@evil.example"],
)
def test_malformed_or_foreign_origin_rejected(client, origin):
    assert client.get("/api/health", headers={"origin": origin}).status_code == 403


@given(st.text(max_size=200))
@settings(max_examples=250, deadline=None)
def test_url_allowlist_never_raises_on_untrusted_text(url):
    assert isinstance(module.allowed_exam(url, module.Profile()), bool)


@pytest.mark.parametrize(
    "expiry", [float("nan"), float("inf"), float("-inf"), True, False, "NaN", None]
)
def test_launch_rejects_non_finite_or_non_numeric_expiry(expiry):
    value = {
        "exp": expiry,
        "nonce": "nonce",
        "userid": "1",
        "quizid": "2",
        "url": "https://localhost/",
    }
    with pytest.raises(ValueError):
        verify_launch(sign_launch(value, KEY), KEY)


@pytest.mark.parametrize(
    "field,bad",
    [("nonce", {}), ("nonce", ["x"]), ("userid", True), ("quizid", []), ("url", 123)],
)
def test_launch_rejects_invalid_claim_types(field, bad):
    value = {
        "exp": time.time() + 60,
        "nonce": "nonce",
        "userid": "1",
        "quizid": "2",
        "url": "https://localhost/",
    }
    value[field] = bad
    with pytest.raises(ValueError):
        verify_launch(sign_launch(value, KEY), KEY)


@pytest.mark.parametrize(
    "stamp", [float("nan"), float("inf"), "NaN", "Infinity", True, None]
)
def test_hub_rejects_invalid_timestamp(client, stamp):
    value = packet()
    value["sent_at"] = stamp
    assert send(client, value).status_code == 422
    assert not module.store.sessions()


@pytest.mark.parametrize(
    "field,bad",
    [
        ("events", [None]),
        ("events", [{}]),
        ("events", {}),
        ("events", "x"),
        ("evidence", []),
        ("reference", "x"),
    ],
)
def test_hub_rejects_malformed_nested_values(client, field, bad):
    value = packet()
    value[field] = bad
    assert send(client, value).status_code == 422
    assert not module.store.sessions()
    assert (
        module.store.db.execute("SELECT count(*) FROM received_packets").fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "field,bad",
    [
        ("id", 123),
        ("created", None),
        ("created", "bad-date"),
        ("ended", {}),
        ("started", "not-a-date"),
        ("data", []),
    ],
)
def test_hub_rejects_malformed_session(client, field, bad):
    value = packet()
    value["session"][field] = bad
    assert send(client, value).status_code == 422
    assert not module.store.sessions()


def test_rejected_packet_does_not_consume_replay_id(client):
    value = packet()
    value["session"]["id"] = "bad"
    assert send(client, value).status_code == 422
    value["session"]["id"] = "a" * 32
    assert send(client, value).status_code == 200
    assert send(client, value).status_code == 409


def test_hub_cannot_move_event_between_sessions(client):
    first = packet()
    original = event(first["session"]["id"])
    first["events"] = [original]
    assert send(client, first).status_code == 200
    module.store.review(original["id"], "confirmed", "Teacher decision")
    second = packet("b" * 32)
    second["events"] = [event("b" * 32, original["id"])]
    assert send(client, second).status_code == 409
    assert module.store.event(original["id"])["session_id"] == "a" * 32
    assert module.store.event(original["id"])["note"] == "Teacher decision"
    assert module.store.session("b" * 32) is None


def test_hub_append_only_history_and_preserves_teacher_verdict(client):
    value = packet()
    original = event(value["session"]["id"])
    value["events"] = [original]
    assert send(client, value).status_code == 200
    module.store.review(original["id"], "dismissed", "Reflection")
    value["packet_id"] = uuid.uuid4().hex
    assert send(client, value).status_code == 200  # Idempotent snapshot.
    assert module.store.event(original["id"])["verdict"] == "dismissed"
    changed = copy.deepcopy(value)
    changed["packet_id"] = uuid.uuid4().hex
    changed["events"] = [
        event(original["session_id"], original["id"], detail={"confidence": 0.01})
    ]
    assert send(client, changed).status_code == 409
    truncated = copy.deepcopy(value)
    truncated["packet_id"] = uuid.uuid4().hex
    truncated["events"] = []
    assert send(client, truncated).status_code == 409
    value["packet_id"] = uuid.uuid4().hex
    value["events"].append(event(original["session_id"], previous=original["hash"]))
    assert send(client, value).status_code == 200
    assert module.store.integrity(original["session_id"])


def test_hub_invalid_base64_rolls_back_everything(client):
    value = packet()
    item = event(value["session"]["id"])
    value["events"] = [item]
    value["evidence"] = {item["id"]: "%%%invalid%%%"}
    assert send(client, value).status_code == 422
    assert not module.store.sessions()
    assert (
        module.store.db.execute("SELECT count(*) FROM received_packets").fetchone()[0]
        == 0
    )


def test_parallel_packets_with_same_replay_id_commit_once(client):
    value = packet()
    module.store.set_setting("hub_receive_key", KEY)
    raw = canonical(value)

    def ingest(_):
        try:
            module.ingest_packet(raw)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(ingest, range(16)))
    assert results.count(200) == 1 and results.count(409) == 15
    assert len(module.store.sessions()) == 1


@pytest.mark.parametrize(
    "chunks,length,status",
    [
        ([b"a" * 16, b"b" * 17], None, 413),
        ([b"a" * 16, b"b" * 17], b"1", 413),
        ([b"a" * 16, b"b" * 16], None, 200),
        ([b""], b"33", 413),
        ([b""], b"-1", 400),
        ([b""], b"bad", 400),
        ([b""], b"0", 200),
        ([b""], b"9" * 5000, 413),
    ],
)
def test_actual_body_limit_including_chunked_and_lying_length(chunks, length, status):
    async def run():
        messages = [
            {"type": "http.request", "body": body, "more_body": i < len(chunks) - 1}
            for i, body in enumerate(chunks)
        ]
        sent = []
        invoked = []

        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        async def target(scope, receive, send):
            invoked.append((await receive())["body"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        scope = {
            "type": "http",
            "method": "POST",
            "headers": [] if length is None else [(b"content-length", length)],
        }
        await RequestBodyLimit(target, max_bytes=32)(scope, receive, send)
        assert sent[0]["status"] == status
        assert invoked == ([b"".join(chunks)] if status == 200 else [])

    asyncio.run(run())


def test_login_rate_limit_is_atomic_under_parallel_requests(client, monkeypatch):
    class SlowRead(dict):
        def get(self, key, default=None):
            value = super().get(key, default)
            time.sleep(
                0.02
            )  # Deterministic opportunity for other threads to reserve attempts.
            return value

    monkeypatch.setattr(module, "login_attempts", SlowRead())
    monkeypatch.setattr(module, "verify_password", lambda *args: False)
    request = SimpleNamespace(client=SimpleNamespace(host="parallel-fixture"))

    def attempt(_):
        try:
            module.login(module.Login(password="wrong"), request, module.Response())
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(attempt, range(12)))
    assert statuses.count(401) == 5
    assert statuses.count(429) == 7


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/sessions", None),
        ("GET", "/api/integration", None),
        ("PUT", "/api/profile", {}),
        ("PUT", "/api/integration/moodle", {"key": "k" * 40}),
        ("PUT", "/api/integration/hub", {}),
        ("POST", "/api/integration/rotate-key", {"kind": "moodle_key"}),
        ("POST", "/api/sessions/" + "a" * 32 + "/stop", {}),
        ("DELETE", "/api/sessions/" + "a" * 32, None),
        ("GET", "/api/sessions/" + "a" * 32 + "/report/json", None),
        ("GET", "/api/events/" + "a" * 32 + "/evidence", None),
        ("PATCH", "/api/events/" + "a" * 32, {"verdict": "confirmed"}),
    ],
)
def test_teacher_endpoints_reject_anonymous_and_expired_cookie(
    client, method, path, body
):
    client.cookies.clear()
    assert client.request(method, path, json=body).status_code == 401
    module.teacher_tokens["expired"] = time.time() - 1
    client.cookies.set("sergek_teacher", "expired")
    assert client.request(method, path, json=body).status_code == 401


@given(st.binary(max_size=4096), st.integers(min_value=0, max_value=4095))
@settings(max_examples=150, deadline=None)
def test_authenticated_evidence_roundtrip_and_bit_tampering(blob, position):
    key = bytes(range(32))
    encrypted = encrypt(blob, key)
    assert decrypt(encrypted, key) == blob
    corrupted = bytearray(encrypted)
    corrupted[15 + position % (len(encrypted) - 15)] ^= 1
    with pytest.raises(InvalidTag):
        decrypt(bytes(corrupted), key)


def test_parallel_event_writers_preserve_complete_chain(client):
    sid = module.store.create_session({"student": "Concurrent", "exam": "Fixture"})[
        "id"
    ]

    def write(index):
        for sequence in range(20):
            module.store.add_event(
                sid, "phone_detected", {"writer": index, "sequence": sequence}
            )

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write, range(16)))
    events = module.store.events(sid)
    assert len(events) == len({e["id"] for e in events}) == 320
    assert module.store.integrity(sid)


def test_disk_failure_rolls_back_hub_database_and_replay_reservation(
    client, monkeypatch, tmp_path
):
    from pathlib import Path

    monkeypatch.setattr(module, "DATA", tmp_path)
    value = packet()
    item = event(value["session"]["id"])
    value["events"] = [item]
    value["evidence"] = {item["id"]: "e30="}

    def full_disk(*args, **kwargs):
        raise OSError("Injected disk full")

    monkeypatch.setattr(Path, "write_bytes", full_disk)
    with pytest.raises(OSError, match="Injected disk full"):
        module.ingest_packet(canonical(value))
    assert not module.store.sessions()
    assert module.store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert (
        module.store.db.execute("SELECT count(*) FROM received_packets").fetchone()[0]
        == 0
    )
