import threading, time, cv2, base64, json, zipfile, io, hashlib, logging
from collections import deque
from .vision import Vision, TemporalRules
from .security import encrypt, decrypt
from concurrent.futures import ThreadPoolExecutor
from .audio import Microphone, wav_bytes, RATE
from .event_policy import review_category


class Engine:
    def __init__(self, store, models, data, key):
        self.store = store
        self.data = data
        self.key = key
        self.vision = None
        self.models = models
        self.load_error = ""
        self.loading = True
        self.sid = None
        self.policy = None
        self.capture = None
        self.stop_event = threading.Event()
        self.thread = None
        self.analysis_thread = self.screen_thread = None
        self.analysis_wakeup = threading.Event()
        self.screen_ready = threading.Event()
        self.vision_lock = threading.RLock()
        self.latest_frame = self.exam_surface = None
        self.frame_serial = 0
        self.analysis_fps = self.screen_fps = 0
        self.screen_error = ""
        self.evidence_error = ""
        self.last_analysis_at = 0
        self.reference = {}
        self.screen_frames = deque()
        self.audio_frames = deque()
        self.microphone = None
        self.writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidence")
        self.writes = []
        self.lock = threading.RLock()
        self.preview = None
        self.signals = {}
        self.frames = deque()
        self.pending = []
        self.rules = TemporalRules()
        self.capture_error = ""
        self.last_frame_at = 0
        self.fps = 0
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            cv2.setNumThreads(2)
            self.vision = Vision(self.models)
            self.load_error = self.vision.error
        except Exception as exc:
            self.load_error = str(exc)
        finally:
            self.loading = False

    def status(self):
        return {
            **(self.microphone.status() if self.microphone else {
                "microphone_running": False, "microphone_error": "", "microphone_dbfs": -96,
            }),
            "models_ready": bool(self.vision and self.vision.ready),
            "loading": self.loading,
            "model_error": self.load_error,
            "camera_running": self.thread is not None and self.thread.is_alive(),
            "camera_error": self.capture_error,
            "fps": round(self.fps, 1),
            "analysis_fps": round(self.analysis_fps, 1),
            "screen_fps": round(self.screen_fps, 1),
            "screen_error": self.screen_error,
            "evidence_error": self.evidence_error,
            "last_analysis_age": (
                round(time.monotonic() - self.last_analysis_at, 1)
                if self.last_analysis_at
                else None
            ),
            "identity_enrolled": bool(self.reference),
            "screen_recording": bool(
                self.screen_thread and self.screen_thread.is_alive()
            ),
            "model": getattr(self.vision, "model_name", None),
            "calibration": self.vision.calibration if self.vision else {},
            "last_frame_age": (
                round(time.monotonic() - self.last_frame_at, 1)
                if self.last_frame_at
                else None
            ),
        }

    def start_camera(self, sid, index, policy):
        self.stop_camera()
        with self.lock:
            self.sid = sid
            self.policy = policy
            self.stop_event.clear()
            self.frames.clear()
            self.screen_frames.clear()
            self.audio_frames.clear()
            self.screen_ready.clear()
            self.latest_frame = self.exam_surface = None
            self.reference = {}
            self.screen_error = ""
            self.evidence_error = ""
            self.last_analysis_at = 0
            self.analysis_fps = self.screen_fps = self.fps = 0
            self.pending.clear()
            self.rules = TemporalRules()
            self.capture_error = ""
            self.preview = None
            self.signals = {}
            self.last_events = {}
            if self.vision:
                with self.vision_lock:
                    self.vision.reset()
                    self.vision.identity_threshold = policy.identity_threshold
                    self.vision.phone_threshold = policy.phone_confidence
        if policy.microphone_required:
            self.microphone = Microphone(self._collect_pending, self.record,
                                         policy.sound_threshold_dbfs, policy.sound_seconds, models=self.models,
                                         noise_threshold=policy.noise_threshold_dbfs)
            self.microphone.start()
        if not policy.camera_required:
            self.capture_error = "Камера өшірілген: бағдарламалық тест профилі"
            return
        self.thread = threading.Thread(target=self._loop, args=(index,), daemon=True)
        self.analysis_thread = threading.Thread(target=self._analyze_loop, daemon=True)
        self.thread.start()
        self.analysis_thread.start()

    def _loop(self, index):
        self.capture = (
            cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if __import__("os").name == "nt"
            else cv2.VideoCapture(index)
        )
        self.capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.capture.set(cv2.CAP_PROP_FPS, 30)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        if not self.capture.isOpened():
            self.capture_error = "Камера ашылмады"
            self.capture.release()
            self.capture = None
            return
        times = deque(maxlen=45)
        last_evidence = 0
        failures = 0
        try:
            while not self.stop_event.is_set():
                ok, frame = self.capture.read()
                if not ok:
                    failures += 1
                    if failures == 5:
                        self.capture_error = "Камера кадры жоғалды"
                        self.record(
                            "camera_disconnected", {"message": self.capture_error}
                        )
                    self.stop_event.wait(0.15)
                    continue
                failures = 0
                self.capture_error = ""
                stamp = time.monotonic()
                self.last_frame_at = stamp
                preview_frame = cv2.resize(frame,(960,round(frame.shape[0]*960/frame.shape[1]))) if frame.shape[1]>960 else frame
                ok, jpeg = cv2.imencode(".jpg", preview_frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
                if not ok:
                    continue
                blob = jpeg.tobytes()
                with self.lock:
                    self.preview = blob
                    self.latest_frame = frame
                    self.frame_serial += 1
                self.analysis_wakeup.set()
                times.append(stamp)
                if len(times) > 1:
                    self.fps = min(
                        120, (len(times) - 1) / max(0.001, times[-1] - times[0])
                    )
                if stamp - last_evidence >= 0.125:
                    self._collect_pending(stamp, blob)
                    last_evidence = stamp
        except Exception as exc:
            logging.exception("Camera pipeline failed")
            self.capture_error = str(exc)
            self.record("camera_pipeline_error", {"message": str(exc)})
        finally:
            self.capture.release()
            self.capture = None

    def _analyze_loop(self):
        serial = -1
        completed = deque(maxlen=90)
        while not self.stop_event.is_set():
            self.analysis_wakeup.wait(0.2)
            self.analysis_wakeup.clear()
            with self.lock:
                if self.latest_frame is None or self.frame_serial == serial:
                    continue
                frame = self.latest_frame.copy()
                serial = self.frame_serial
            if not self.vision or not self.vision.ready:
                continue
            stamp = time.monotonic()
            try:
                with self.vision_lock:
                    self.vision.identity_threshold = self.policy.identity_threshold
                    self.vision.phone_threshold = self.policy.phone_confidence
                    signals, _ = self.vision.analyze(frame)
                with self.lock:
                    self.signals = signals
                    self.last_analysis_at = time.monotonic()
                completed.append(time.monotonic())
                while len(completed) > 2 and completed[-1] - completed[0] > 3:
                    completed.popleft()
                self.analysis_fps = ((len(completed) - 1) / max(0.001, completed[-1] - completed[0])) if len(completed) > 1 else 0
                item = self.store.session(self.sid) if self.sid else None
                if item and item["status"] == "active":
                    for kind, detail in self.rules.update(
                        signals, self.policy, time.monotonic()
                    ):
                        self.record(kind, detail)
            except Exception as exc:
                logging.exception("AI worker failed")
                self.capture_error = "AI өңдеу қатесі: " + str(exc)
                self.record("camera_pipeline_error", {"message": str(exc)})
                self.stop_event.wait(0.3)

    def enroll(self):
        with self.lock:
            if self.latest_frame is None or time.monotonic() - self.last_frame_at > 1:
                raise ValueError("Камераның жаңа кадры қажет.")
            if self.signals.get("faces") != 1 or self.signals.get("quality") != "good":
                raise ValueError("Камерада бір бет анық көрінуі қажет.")
            frame = self.latest_frame.copy()
            vector = [self.signals.get(k) for k in ["yaw", "pitch", "iris"]]
        with self.vision_lock:
            embedding = self.vision.identity.enroll(frame)
            if all(v is not None for v in vector):
                self.vision.calibration = {"center": vector}
        _, photo = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        self.reference = {
            "photo": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
            "enrolled_at": time.time(),
        }
        path = self.data / "reference" / (self.sid + ".sg")
        path.parent.mkdir(exist_ok=True)
        payload = {**self.reference, "embedding": embedding.tolist(), "model": "SFace"}
        path.write_bytes(encrypt(json.dumps(payload).encode(), self.key))
        self.store.update_session(
            self.sid,
            patch={
                "identity_reference": path.name,
                "identity_model": "SFace",
                "identity_enrolled_at": self.reference["enrolled_at"],
            },
        )
        return self.reference

    def start_recording(self):
        if not self.policy.screen_recording:
            return
        if self.screen_thread and self.screen_thread.is_alive():
            if not self.screen_ready.is_set():
                raise ValueError("Экран жазбасы әлі дайын емес")
            return
        self.screen_error = ""
        self.screen_ready.clear()
        self.screen_thread = threading.Thread(target=self._screen_loop, daemon=True)
        self.screen_thread.start()
        if not self.screen_ready.wait(4) or self.screen_error:
            raise ValueError(self.screen_error or "Экран жазбасы дайын емес")

    def retry_microphone(self):
        if not self.policy.microphone_required:
            return self.status()
        if self.microphone and not self.microphone.status().get("microphone_error"):
            return self.status()
        if self.microphone:
            self.microphone.close()
        self.audio_frames.clear()
        self.microphone = Microphone(self._collect_pending, self.record,
                                     self.policy.sound_threshold_dbfs, self.policy.sound_seconds, models=self.models,
                                     noise_threshold=self.policy.noise_threshold_dbfs)
        self.microphone.start()
        return self.status()

    def set_exam_surface(self, image, bounds):
        if len(image) > 2_000_000:
            raise ValueError("Exam frame too large")
        with self.lock:
            self.exam_surface = (bytes(image), bounds, time.monotonic())

    def _screen_loop(self):
        from PIL import ImageGrab, Image

        times = deque(maxlen=20)
        try:
            while not self.stop_event.is_set():
                start = time.monotonic()
                image = ImageGrab.grab(all_screens=False).convert("RGB")
                with self.lock:
                    surface = self.exam_surface
                # Own page pixels come from trusted capturePage. Windows protection stays on.
                if surface and start - surface[2] < 1.5:
                    own = Image.open(io.BytesIO(surface[0])).convert("RGB")
                    b = surface[1]
                    own = own.resize((int(b["width"]), int(b["height"])))
                    image.paste(own, (int(b["x"]), int(b["y"])))
                image.thumbnail((1280, 720))
                buf = io.BytesIO()
                image.save(buf, "JPEG", quality=65)
                self._collect_pending(start, buf.getvalue(), "screen")
                times.append(start)
                if len(times) > 1:
                    self.screen_fps = (len(times) - 1) / max(
                        0.001, times[-1] - times[0]
                    )
                self.screen_error = ""
                self.screen_ready.set()
                self.stop_event.wait(max(0, 0.2 - (time.monotonic() - start)))
        except Exception as exc:
            self.screen_error = "Экран жазбасы қолжетімсіз: " + str(exc)
            self.screen_ready.set()
            self.record("screen_capture_error", {"message": self.screen_error})

    def record(self, kind, detail):
        with self.lock:
            if not self.sid:
                return None
            item = self.store.session(self.sid)
            if not item or (
                item["status"] != "active"
                and not (
                    item["status"] == "preflight"
                    and kind
                    in (
                        "application_closed",
                        "application_close_failed",
                        "remote_control_blocked",
                        "remote_enforcement_failed",
                    )
                )
            ):
                return None
            # Desktop/device events may repeat; collapse identical observations for 2s.
            now = time.monotonic()
            if not hasattr(self, "last_events"):
                self.last_events = {}
            dedup = kind + ":" + str(detail.get("pid", detail.get("name", "")))
            if now - self.last_events.get(dedup, -100) < 2:
                return None
            self.last_events[dedup] = now
            detail = dict(detail)
            detail["phase"] = item["status"]
            screen_jpeg = detail.pop("screen_jpeg", None)
            if self.signals:
                detail = {**detail, "context": dict(self.signals)}
            event = self.store.add_event(self.sid, kind, detail)
            if review_category(kind, detail) == "technical":
                return event
            tracks = {"camera": list(self.frames), "screen": list(self.screen_frames),
                      "audio": list(self.audio_frames)}
            if screen_jpeg and self.policy.screen_recording:
                try:
                    image = base64.b64decode(screen_jpeg, validate=True)
                    if image[:2] == b"\xff\xd8" and len(image) < 2_000_000:
                        tracks["screen"].append((now, image))
                except ValueError:
                    pass
            self.pending.append(
                {
                    "id": event["id"],
                    "tracks": tracks,
                    "end": now + self.policy.post_seconds,
                    "started": now,
                }
            )
            return event

    def _collect_pending(self, stamp, blob, track="camera"):
        finished = []
        with self.lock:
            buffer = {"camera": self.frames, "screen": self.screen_frames,
                      "audio": self.audio_frames}[track]
            buffer.append((stamp, blob))
            while buffer and stamp - buffer[0][0] > self.policy.pre_seconds:
                buffer.popleft()
            for capture in self.pending:
                capture["tracks"].setdefault(track, []).append((stamp, blob))
                if stamp >= capture["end"]:
                    finished.append(capture)
            self.pending = [c for c in self.pending if c not in finished]
        for capture in finished:
            self.writes = [f for f in self.writes if not f.done()]
            self.writes.append(self.writer.submit(self._save_evidence, capture))
            self.writes[-1].add_done_callback(
                lambda future, event_id=capture["id"]: self._write_done(
                    future, event_id
                )
            )

    def _write_done(self, future, event_id):
        try:
            future.result()
        except Exception as exc:
            self.evidence_error = "Дәлелді сақтау қатесі: " + str(exc)
            logging.exception("Evidence write failed")
            self.store.audit(
                "evidence_write_failed", {"event_id": event_id, "error": str(exc)}
            )

    def _save_evidence(self, capture):
        tracks = capture.get("tracks", {"camera": capture.get("frames", [])})
        present = [v for v in tracks.values() if v]
        if not present:
            return
        stream = io.BytesIO()
        start = min(v[0][0] for v in present)
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as archive:
            manifests = {}
            audio_manifest = None
            for track, values in tracks.items():
                values = sorted(values, key=lambda value: value[0])
                if track == "audio":
                    if values:
                        archive.writestr("audio.wav", wav_bytes(values))
                        audio_manifest = {"file": "audio.wav", "sample_rate": RATE,
                                          "time": round(values[0][0] - start, 3),
                                          "duration": sum(len(v[1]) for v in values) / (RATE * 2)}
                    continue
                rows = []
                for i, (stamp, blob) in enumerate(values):
                    filename = f"{track}/{i:04d}.jpg"
                    archive.writestr(filename, blob)
                    rows.append({"file": filename, "time": round(stamp - start, 3)})
                manifests[track] = rows
            primary = "camera" if manifests.get("camera") else "screen"
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "event_id": capture["id"],
                        "tracks": manifests,
                        "primary": primary,
                        "frames": manifests[primary],
                        "event_offset": round(capture["started"] - start, 3),
                        "audio": audio_manifest,
                    }
                ),
            )
        encrypted = encrypt(stream.getvalue(), self.key)
        path = self.data / "evidence" / f"{capture['id']}.sg"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(encrypted)
        self.store.attach_media(capture["id"], path.name)
        self.store.audit(
            "evidence_saved",
            {
                "event_id": capture["id"],
                "sha256": hashlib.sha256(encrypted).hexdigest(),
                "tracks": {k: len(v) for k, v in tracks.items()},
            },
        )

    def _flush_pending(self):
        with self.lock:
            captures = self.pending
            self.pending = []
        for capture in captures:
            self._save_evidence(capture)

    def evidence(self, event):
        path = self.data / "evidence" / event["media"]
        raw = decrypt(path.read_bytes(), self.key)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("audio"):
                manifest["audio"]["src"] = "data:audio/wav;base64," + base64.b64encode(
                    archive.read(manifest["audio"]["file"])).decode()
            tracks = manifest.get("tracks", {"camera": manifest["frames"]})
            for frames in tracks.values():
                for frame in frames:
                    frame["image"] = (
                        "data:image/jpeg;base64,"
                        + base64.b64encode(archive.read(frame["file"])).decode()
                    )
            manifest["tracks"] = tracks
            manifest["frames"] = tracks.get(manifest.get("primary", "camera")) or next(
                (v for v in tracks.values() if v), []
            )
        return manifest

    def stop_camera(self):
        self.stop_event.set()
        if self.microphone:
            self.microphone.close()
            self.microphone = None
        self.analysis_wakeup.set()
        for thread in (self.thread, self.analysis_thread, self.screen_thread):
            if thread and thread.is_alive():
                thread.join(timeout=4)
            if thread and thread.is_alive():
                raise RuntimeError("Capture worker did not stop; restart application")
        self._flush_pending()
        for future in self.writes:
            try:
                future.result(timeout=15)
            except Exception as exc:
                self.evidence_error = "Дәлелді сақтау қатесі: " + str(exc)
        self.writes = []
        self.thread = self.analysis_thread = self.screen_thread = None
        self.sid = None

    def snapshot(self, include_preview=True):
        with self.lock:
            return {
                "signals": self.signals,
                "identity": dict(self.reference),
                "preview": (
                    "data:image/jpeg;base64," + base64.b64encode(self.preview).decode()
                    if self.preview and include_preview
                    else None
                ),
                "status": self.status(),
            }
