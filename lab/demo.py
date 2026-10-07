"""Prepare the judge demo, keeping credentials outside distributable source."""
import os, json, sys
from pathlib import Path
from setup import LAB, ROOT


def prepare_demo(destination=None):
    from backend.config import Profile, HubConfig
    meta = json.loads((LAB / "lab.json").read_text(encoding="utf-8"))
    creds = json.loads((LAB / "credentials.json").read_text(encoding="utf-8"))
    target = Path(destination or LAB / "demo-config.json").resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    p = Profile(tls_pins={"localhost": meta["fingerprint"]})
    config = {
        "data": str(target.parent / "demo-agent"),
        "ca_file": str(LAB / "localhost.crt"),
        "profile": p.model_dump(),
        "hub": HubConfig(enabled=True, url=meta["hub"], pairing_key=creds["hubkey"]).model_dump(),
        "moodle_key": creds["sharedkey"],
        "teacher_password": creds["teacherpass"],
    }
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    login_file = target.parent / "Demo-login.txt"
    login_file.write_text(
        "Sergек — локалды таныстыру ортасы\nMoodle: https://localhost/\n\n"
        f"Студент логині: {creds['student']}\nСтудент құпиясөзі: {creds['studentpass']}\n\n"
        f"Moodle мұғалімінің логині: {creds.get('moodle_teacher','')}\nMoodle мұғалімінің құпиясөзі: {creds.get('moodle_teacher_password','')}\n\n"
        f"Мұғалім панелінің құпиясөзі: {creds['teacherpass']}\n\n"
        "Қосымшада «Moodle-ға кіру» → логин → курс → тест → келісім → фото → «Тест бетіне өту» → Moodle-дегі «Start attempt».\n"
        "Қорғаныс Moodle тесті басталғанда автоматты қосылады. Дайындық алдында ашық жұмысыңызды сақтаңыз.\n"
        "Бұл тіркелгі тек осы компьютердегі локалды ортаға арналған.\n",
        encoding="utf-8",
    )
    return target


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    if "--prepare-only" not in sys.argv:
        os.environ["SERGEK_LAB_MODE"] = "strict"
        from start import start
        start()
    target = prepare_demo()
    result = next((arg.split("=",1)[1] for arg in sys.argv if arg.startswith("--config-result=")), "")
    if result:
        Path(result).write_text(json.dumps({"config":str(target)}), encoding="utf-8")
    if "--configure" in sys.argv:
        pointer = Path(os.environ["APPDATA"]) / "sergek-proctor" / "demo-launch.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps({"config": str(target)}), encoding="utf-8")
    print("Local demo configured. Credentials file:", target.parent / "Demo-login.txt")
