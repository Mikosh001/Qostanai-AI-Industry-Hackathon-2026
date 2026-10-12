"""Validate the complete untrusted snapshot before database or media writes."""

import base64
import json
import math
import time
from datetime import datetime


def reject_constant(value):
    raise ValueError("Non-finite JSON number")


def hex_id(value, length=32):
    return (
        isinstance(value, str)
        and len(value) == length
        and all(c in "0123456789abcdef" for c in value)
    )


def timestamp(value, nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise ValueError("Invalid session timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp timezone required")


def validate_packet(raw):
    packet = json.loads(raw, parse_constant=reject_constant)
    if not isinstance(packet, dict) or not hex_id(packet.get("packet_id")):
        raise ValueError("Invalid packet ID")
    sent = packet.get("sent_at")
    if (
        isinstance(sent, bool)
        or not isinstance(sent, (int, float))
        or not 0 < sent < 1e12
        or not math.isfinite(sent)
        or abs(time.time() - sent) > 30
    ):
        raise ValueError("Expired or invalid packet timestamp")
    item = packet.get("session")
    if not isinstance(item, dict) or not hex_id(item.get("id")):
        raise ValueError("Invalid session ID")
    if item.get("status") not in (
        "preflight",
        "active",
        "completed",
        "interrupted",
    ) or not isinstance(item.get("data"), dict):
        raise ValueError("Invalid session")
    timestamp(item.get("created"))
    timestamp(item.get("ended"), nullable=True)
    timestamp(item.get("started"), nullable=True)
    timestamp(item["data"].get("active_started_at"), nullable=True)
    events = packet.get("events", [])
    if not isinstance(events, list):
        raise ValueError("Events must be a list")
    ids = set()
    for event in events:
        if (
            not isinstance(event, dict)
            or not hex_id(event.get("id"))
            or event["id"] in ids
        ):
            raise ValueError("Invalid or duplicate event ID")
        ids.add(event["id"])
        if event.get("session_id") != item["id"] or not isinstance(
            event.get("detail"), dict
        ):
            raise ValueError("Invalid event session or detail")
        if not isinstance(event.get("kind"), str) or not 1 <= len(event["kind"]) <= 64:
            raise ValueError("Invalid event kind")
        timestamp(event.get("created"))
        if not hex_id(event.get("hash"), 64) or not hex_id(
            event.get("previous_hash"), 64
        ):
            raise ValueError("Invalid event hash")
    evidence = packet.get("evidence", {})
    if not isinstance(evidence, dict) or ("cursor" not in packet and not set(evidence).issubset(ids)) or any(not hex_id(k) for k in evidence):
        raise ValueError("Evidence must belong to snapshot events")
    decoded = {}
    total = 0
    for eid, blob in evidence.items():
        if not isinstance(blob, str):
            raise ValueError("Evidence must be base64 text")
        decoded[eid] = base64.b64decode(blob, validate=True)
        total += len(decoded[eid])
        if total > 12_000_000:
            raise ValueError("Evidence budget exceeded")
    reference = packet.get("reference")
    if reference is not None and (
        not isinstance(reference, dict) or not isinstance(reference.get("photo"), str)
    ):
        raise ValueError("Invalid reference photo")
    return packet, decoded
