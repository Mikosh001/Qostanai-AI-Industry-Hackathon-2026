"""Acceptance fixture: generated PCM tone, no physical microphone/camera or OS restrictions."""
import sys, threading, time, wave
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.audio import Microphone, RATE
from backend import engine as engine_module

class GeneratedPCM(Microphone):
    def start(self):
        self.thread=threading.Thread(target=self.generate,daemon=True)
        self.thread.start()
        self.ready.wait(2)
    def generate(self):
        with wave.open(str(Path(__file__).parent / "speech.wav")) as sound:
            raw=sound.readframes(sound.getnframes())
        samples=[raw[i:i+3200].ljust(3200,b'\0') for i in range(0,len(raw),3200)]
        i=0
        while not self.stop.wait(.1):
            position=i%(len(samples)+30)
            self.process(time.monotonic(), samples[position-30] if position>=30 else bytes(3200))
            i+=1
    def status(self):
        return {"microphone_running":bool(self.thread and self.thread.is_alive()),
                "microphone_error":self.error,"microphone_dbfs":self.level}
engine_module.Microphone=GeneratedPCM
from backend import app as module
from backend.config import Profile
from backend.security import hash_password
p=Profile(exam_mode="monitor")
p.policy.camera_required=False
p.policy.screen_recording=False
p.policy.post_seconds=3
module.store.set_setting("profile",p.model_dump())
module.store.set_setting("password",hash_password("AudioAcceptance123!"))
import uvicorn
uvicorn.run(module.app,host="127.0.0.1",port=8772,access_log=False)
