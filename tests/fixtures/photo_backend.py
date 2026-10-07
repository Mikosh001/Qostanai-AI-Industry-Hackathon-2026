"""Acceptance only: public image fixture, no webcam, screen capture or Windows restrictions."""

import os, sys, time
from pathlib import Path
import cv2
import numpy as np

project = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project))
fixture = Path(os.environ["SERGEK_PHOTO_FIXTURE"])


class Capture:
    def __init__(self, *args):
        self.images = {
            k: cv2.resize(cv2.imread(str(fixture / k)), (640, 480))
            for k in ["portrait.jpg", "lena.jpg"]
        }
        if os.environ.get("SERGEK_PHONE_IMAGE"):
            phone = cv2.imread(os.environ["SERGEK_PHONE_IMAGE"])
            if phone is None: raise ValueError("Phone fixture unreadable")
            height,width=phone.shape[:2]; scale=min(640/width,480/height)
            resized=cv2.resize(phone,(round(width*scale),round(height*scale)))
            canvas=np.full((480,640,3),114,np.uint8)
            y=(480-resized.shape[0])//2;x=(640-resized.shape[1])//2
            canvas[y:y+resized.shape[0],x:x+resized.shape[1]]=resized
            self.images["phone.jpg"] = canvas

    def set(self, *args):
        pass

    def isOpened(self):
        return True

    def read(self):
        time.sleep(1 / 30)
        return (
            True,
            self.images.get(
                (fixture / "choice.txt").read_text().strip(),
                self.images["portrait.jpg"],
            ).copy(),
        )

    def release(self):
        pass


cv2.VideoCapture = Capture
from backend import app as module
from backend.config import Profile
from backend.security import hash_password

p = Profile()
p.policy.screen_recording = False
p.policy.microphone_required = False
p.exam_mode = "monitor"
legacy = p.model_dump()
legacy["policy"]["liveness_required"] = True  # Old saved settings must not restore the removed gate.
module.store.set_setting("profile", legacy)
module.store.set_setting("password", hash_password("PhotoAcceptance123!"))
import uvicorn

uvicorn.run(module.app, host="127.0.0.1", port=8771, access_log=False)
