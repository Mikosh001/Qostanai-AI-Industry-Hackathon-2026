from pathlib import Path
from pydantic import BaseModel, Field, HttpUrl
from typing import Literal
import os

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("SERGEK_DATA", str(ROOT / "runtime")))
MODELS = Path(os.environ.get("SERGEK_MODELS", str(ROOT / "models")))
DESKTOP_KEY = os.environ.get("SERGEK_DESKTOP_KEY", "")


class Policy(BaseModel):
    name: str = "Қорғалған емтихан"
    camera_required: bool = True
    microphone_required: bool = True
    sound_threshold_dbfs: float = Field(-35, ge=-70, le=-10)
    sound_seconds: float = Field(4, ge=3, le=15)
    noise_threshold_dbfs: float = Field(-12, ge=-30, le=-3)
    identity_threshold: float = Field(0.363, ge=0.1, le=0.9)
    identity_seconds: float = Field(2.5, ge=1, le=15)
    screen_recording: bool = True
    close_applications: bool = True
    remote_block: bool = True
    usb_block: bool = True
    keyboard_block: bool = True
    single_monitor: bool = True
    paper_allowed: bool = False
    copy_paste: bool = False
    phone_confidence: float = Field(0.30, ge=0.25, le=0.95)
    phone_seconds: float = Field(2.0, ge=0.2, le=30)
    gaze_seconds: float = Field(8.0, ge=1, le=60)
    absence_seconds: float = Field(3.0, ge=1, le=60)
    multi_face_seconds: float = Field(1.5, ge=0.2, le=30)
    retention_days: int = Field(14, ge=1, le=365)
    forbidden_processes: list[str] = Field(
        default_factory=lambda: [
            "anydesk.exe",
            "teamviewer.exe",
            "discord.exe",
            "telegram.exe",
            "chrome.exe",
            "msedge.exe",
            "firefox.exe",
            "rustdesk.exe",
            "anydesk_service.exe",
            "teamviewer_service.exe",
            "quickassist.exe",
            "msra.exe",
            "mstsc.exe",
            "vncserver.exe",
            "winvnc.exe",
            "tvnserver.exe",
            "parsecd.exe",
            "aeroadmin.exe",
            "screenconnect.clientservice.exe",
            "splashtop-streamer.exe",
            "strwinclt.exe",
            "logmein.exe",
            "dwagent.exe",
        ]
    )
    pre_seconds: int = Field(5, ge=1, le=15)
    post_seconds: int = Field(5, ge=1, le=15)


class Profile(BaseModel):
    exam_mode: Literal["strict", "monitor"] = "strict"
    university: str = "Sergек · таныстыру ортасы"
    moodle_url: str = "https://localhost/"
    platonus_url: str = "https://localhost/"
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost"]
    )
    tls_pins: dict[str, str] = Field(default_factory=dict)
    policy: Policy = Field(default_factory=Policy)


class SessionCreate(BaseModel):
    student: str = Field(min_length=2, max_length=120)
    exam: str = Field(min_length=2, max_length=160)
    platform: Literal["local", "moodle", "platonus"] = "local"
    exam_url: str = ""
    camera_index: int = Field(0, ge=0, le=16)
    launch_token: str = ""
    consent: bool = False
    mode: Literal["monitor", "strict"] = "strict"


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class Review(BaseModel):
    verdict: Literal["pending", "confirmed", "dismissed"]
    note: str = Field("", max_length=2000)


class CalibrationPoint(BaseModel):
    direction: Literal["center", "left", "right", "down"]


class AgentEvent(BaseModel):
    kind: str = Field(min_length=1, max_length=64)
    detail: dict = Field(default_factory=dict)


class HubConfig(BaseModel):
    url: str = ""
    pairing_key: str = ""
    enabled: bool = False
