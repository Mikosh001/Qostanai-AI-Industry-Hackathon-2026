"""Disposable backend for browser acceptance; no camera or Windows guard."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SERGEK_DATA"] = tempfile.mkdtemp(prefix="sergek-browser-")
os.environ["SERGEK_DESKTOP_KEY"] = "browser-fixture-only"
os.environ.pop("SERGEK_DEMO_CONFIG", None)
from backend import app as module
from backend.security import hash_password
module.store.set_setting("password", hash_password(os.environ.get("SERGEK_TEST_PASSWORD", "AcceptanceTeacher123!")))
session=module.store.create_session({'student':'Review fixture','exam':'Filtering acceptance','platform':'local'})
module.store.add_event(session['id'],'navigation_blocked',{'host':'cdn.jsdelivr.net'})
module.store.add_event(session['id'],'sound_activity',{'level_dbfs':-25})
module.store.add_event(session['id'],'phone_detected',{'confidence':0.91,'duration_seconds':3})
module.store.add_event(session['id'],'application_closed',{'phase':'active','blocked':True,'name':'fixture.exe'})
module.store.add_event(session['id'],'remote_control_blocked',{'phase':'active','restarted_then_stopped':True})
module.store.update_session(session['id'],'completed')
import uvicorn
uvicorn.run(module.app, host="127.0.0.1", port=8765, access_log=False)
