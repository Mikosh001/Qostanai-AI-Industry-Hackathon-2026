"""Local microphone capture. The PortAudio callback only copies PCM into a queue."""
import io
import queue
import threading
import time
import wave
from collections import deque
import numpy as np


RATE = 16000


def wav_bytes(chunks):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(RATE)
        audio.writeframes(b"".join(blob for _, blob in chunks))
    return output.getvalue()


class Microphone:
    def __init__(self, consume, notify, threshold=-35, seconds=4, models=None, detector=None, noise_threshold=-12):
        self.consume, self.notify = consume, notify
        self.threshold, self.seconds = threshold, max(3, seconds)
        self.stream = self.thread = None
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.queue = queue.Queue(maxsize=50)
        self.error = ""
        self.level = -96.0
        self.last_frame = 0
        self.since = None
        self.last_event = -100
        self.models, self.detector = models, detector
        self.speech_probability = 0.0
        self.voiced_seconds = 0.0
        self.last_voice = None
        self.episode_emitted = False
        self.dropouts = deque()
        self.dropout_count = 0
        self.noise_threshold = noise_threshold
        self.noise_seconds = 0.0
        self.last_noise = None
        self.noise_emitted = False

    def ensure_detector(self):
        if self.detector is None:
            from .speech import SpeechDetector
            from .config import MODELS
            self.detector = SpeechDetector(self.models or MODELS)

    def start(self):
        try:
            import sounddevice as sd
            self.ensure_detector()
            self.stream = sd.RawInputStream(
                samplerate=RATE, channels=1, dtype="int16", blocksize=1600,
                callback=self.callback,
            )
            self.thread = threading.Thread(target=self.run, daemon=True, name="microphone")
            self.thread.start()
            self.stream.start()
            if not self.ready.wait(3) or self.error:
                raise ValueError(self.error or "Микрофоннан дыбыс келмеді")
        except Exception as exc:
            self.error = "Микрофон қолжетімсіз: " + str(exc)
            self.close()

    def callback(self, data, frames, timing, status):
        if self.stop.is_set():
            return
        if status:
            self.note_dropout()
        try:
            self.queue.put_nowait((time.monotonic(), bytes(data)))
        except queue.Full:
            self.note_dropout()
            # Keep fresh audio, never accumulate a multi-second stale backlog.
            try: self.queue.get_nowait()
            except queue.Empty: pass
            try: self.queue.put_nowait((time.monotonic(), bytes(data)))
            except queue.Full: pass

    def note_dropout(self):
        self.dropout_count += 1
        self.dropouts.append(time.monotonic())

    def process(self, stamp, pcm):
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) else 0
        self.level = round(20 * np.log10(max(rms, 1e-5)), 1)
        gap = stamp - self.last_frame if self.last_frame else 0
        self.ensure_detector()
        if gap > 0.5:
            self.detector.reset()
            self.reset_episode()
            self.noise_seconds, self.last_noise, self.noise_emitted = 0.0, None, False
        self.last_frame = stamp
        self.consume(stamp, pcm, "audio")
        self.speech_probability = self.detector.probability(samples)
        duration = len(samples) / RATE
        voiced = self.level >= self.threshold and self.speech_probability >= 0.8
        if self.level >= self.noise_threshold and not voiced:
            self.last_noise = stamp
            self.noise_seconds += duration
            if self.noise_seconds >= self.seconds and not self.noise_emitted:
                self.noise_emitted = True
                self.notify("sustained_noise", {"detector": "sustained-loudness-v1",
                    "level_dbfs": self.level, "noise_seconds": round(self.noise_seconds, 2),
                    "threshold_dbfs": self.noise_threshold,
                    "meaning": "Sustained loud non-speech sound; review audio, no speaker attribution."})
        elif self.last_noise is None or stamp - self.last_noise >= 1.2:
            self.noise_seconds, self.last_noise, self.noise_emitted = 0.0, None, False
        if voiced:
            if self.since is None:
                self.since = stamp
            self.last_voice = stamp
            self.voiced_seconds += duration
            if self.voiced_seconds >= self.seconds and not self.episode_emitted and stamp - self.last_event >= 60:
                self.last_event = stamp
                self.episode_emitted = True
                self.notify("sound_activity", {
                    "level_dbfs": self.level, "duration_seconds": round(stamp - self.since, 1),
                    "voiced_seconds": round(self.voiced_seconds, 2),
                    "speech_probability": round(self.speech_probability, 3),
                    "detector": "silero-vad-6.0",
                    "meaning": "Sustained possible speech; teacher reviews the recording. Speaker and cheating are not determined.",
                })
        elif self.last_voice is None or stamp - self.last_voice >= 1.2:
            self.reset_episode()
        self.ready.set()

    def reset_episode(self):
        self.since = self.last_voice = None
        self.voiced_seconds = 0.0
        self.episode_emitted = False

    def run(self):
        while not self.stop.is_set():
            try:
                self.process(*self.queue.get(timeout=0.2))
            except queue.Empty:
                continue
            except Exception as exc:
                self.error = "Микрофон өңдеу қатесі: " + str(exc)
                self.ready.set()
                break

    def status(self):
        age = time.monotonic() - self.last_frame if self.last_frame else None
        running = bool(self.stream and self.stream.active and self.thread and self.thread.is_alive())
        error = self.error
        now = time.monotonic()
        while self.dropouts and now - self.dropouts[0] > 5:
            self.dropouts.popleft()
        if len(self.dropouts) >= 4:
            error = error or "Микрофон ағынында қайталанған дерек жоғалуы"
        if self.ready.is_set() and (not running or age is None or age > 3):
            error = error or "Микрофон ағыны тоқтады"
        return {"microphone_running": running, "microphone_error": error,
                "microphone_dbfs": self.level, "microphone_age": age,
                "speech_probability": round(self.speech_probability,3), "audio_dropouts": self.dropout_count}

    def close(self):
        self.stop.set()
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=3)
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Microphone worker did not stop")
