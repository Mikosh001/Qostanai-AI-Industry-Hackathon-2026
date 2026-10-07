"""Review metadata is derived separately from the immutable observation/hash."""
OBSERVATIONS = {"phone_detected", "phone_raised", "identity_mismatch", "face_absent",
                "multiple_faces", "gaze_down", "gaze_side", "camera_obscured", "sustained_noise", "presentation_attack"}
SYSTEM_FAILURES = {"application_close_failed", "remote_enforcement_failed", "storage_enforcement_failed",
                   "camera_disconnected", "microphone_disconnected", "camera_pipeline_error",
                   "screen_capture_error", "guard_lost", "exam_renderer_crashed", "session_interrupted", "evidence_write_failed"}


def review_category(kind, detail=None):
    detail = detail or {}
    # Successful prevention is a technical action, never student evidence.
    if kind.endswith("_blocked") or kind in {"application_closed", "remote_control_stopped"} or detail.get("blocked") is True:
        return "technical"
    if kind in SYSTEM_FAILURES:
        return "system"
    if kind in OBSERVATIONS:
        return "observation"
    if kind == "sound_activity":
        # Earlier RMS-only records remain visible in the technical journal.
        return "observation" if detail.get("detector") == "silero-vad-6.0" else "technical"
    if kind == "foreground_changed" and detail.get("trusted") is False and detail.get("prevention_active") is False and detail.get("phase") == "active":
        return "observation"
    if kind in {"remote_control", "forbidden_process"} and detail.get("phase") == "active" and detail.get("blocked") is False:
        return "observation"
    return "technical"


def annotate(event):
    category = review_category(event["kind"], event.get("detail"))
    return {**event, "category": category, "requires_review": category != "technical"}
