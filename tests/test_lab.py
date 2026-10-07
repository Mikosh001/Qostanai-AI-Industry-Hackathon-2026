import importlib.util, sys
from pathlib import Path
from types import SimpleNamespace


def load_lab():
    folder=Path(__file__).resolve().parent.parent/'lab'
    sys.path.insert(0,str(folder))
    try:
        spec=importlib.util.spec_from_file_location('sergek_lab_start',folder/'start.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module
    finally:sys.path.remove(str(folder))


def test_reused_pid_is_not_a_lab_helper(monkeypatch):
    module=load_lab()
    alien=SimpleNamespace(exe=lambda:'C:/Windows/System32/notepad.exe',cmdline=lambda:['notepad.exe'],environ=lambda:{})
    monkeypatch.setattr(module.psutil,'Process',lambda pid:alien)
    assert module.owned_process('tls',123) is None
    assert module.owned_process('hub',123) is None
    assert module.owned_process('db',123) is None


def test_owned_helper_requires_exact_environment_and_command(monkeypatch):
    module=load_lab()
    helper=SimpleNamespace(exe=lambda:sys.executable,cmdline=lambda:[sys.executable,str(module.ROOT/'lab'/'proxy.py')],environ=lambda:{'SERGEK_LAB':str(module.LAB)})
    monkeypatch.setattr(module.psutil,'Process',lambda pid:helper)
    assert module.owned_process('tls',123) is helper
    assert module.owned_process('hub',123) is None


def test_base_runtime_helpers_are_owned_without_a_venv_redirector(monkeypatch):
    module=load_lab()
    args=[sys._base_executable,str(module.ROOT/'lab/runtime.py'),sys.executable,'--module','backend.run','--port','9443']
    helper=SimpleNamespace(exe=lambda:sys._base_executable,cmdline=lambda:args,environ=lambda:{'SERGEK_LAB':str(module.LAB)})
    monkeypatch.setattr(module.psutil,'Process',lambda pid:helper)
    assert module.owned_process('hub',123) is helper
    assert module.owned_process('tls',123) is None


def test_lab_preference_transport_preserves_auth_and_other_bodies(monkeypatch):
    module=load_lab();monkeypatch.setenv('SERGEK_LAB',str(module.LAB))
    spec=importlib.util.spec_from_file_location('sergek_lab_proxy',module.ROOT/'lab'/'proxy.py')
    proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)
    path='r.php/api/rest/v2/user/current/preferences/qbank_managecategories_includesubcategories_filter_default'
    assert proxy.preference_body(path,b'{"value":false}')==b'{"value":"0"}'
    assert proxy.preference_body(path,b'{"value":""}')==b'{"value":"0"}'
    assert proxy.preference_body(path,b'{"value":true}')==b'{"value":true}'
    assert proxy.preference_body('other/path',b'{"value":false}')==b'{"value":false}'
    assert proxy.preference_body(path,b'{"value":false,"other":1}')==b'{"value":false,"other":1}'


def test_late_anonymous_cookie_cannot_replace_a_successful_moodle_login(monkeypatch):
    module=load_lab();monkeypatch.setenv('SERGEK_LAB',str(module.LAB))
    spec=importlib.util.spec_from_file_location('sergek_lab_proxy_cookie',module.ROOT/'lab'/'proxy.py')
    proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)
    tracker=proxy.CookieRotations()
    login=[(b'Set-Cookie',b'MoodleSession=fresh; Path=/; Secure; HttpOnly'),(b'Location',b'/login/index.php?testsession=5')]
    assert tracker.filter('POST','login/index.php',303,'MoodleSession=old',login,now=1)==login
    late=[(b'Set-Cookie',b'MoodleSession=anonymous; Path=/; Secure; HttpOnly'),(b'X-Test',b'preserved')]
    assert tracker.filter('GET','lib/ajax/service-nologin.php',200,'MoodleSession=old',late,now=2)==[(b'X-Test',b'preserved')]
    # Genuine logout/expired/new sessions must still work. Never transfer fresh
    # authentication to old requests or weaken Moodle's login validation.
    assert tracker.filter('GET','login/logout.php',303,'MoodleSession=fresh',late,now=2)==late
    assert tracker.filter('GET','login/index.php',200,'MoodleSession=other',late,now=2)==late
    assert tracker.filter('GET','login/index.php',200,'MoodleSession=old',late,now=122)==late
    tracker=proxy.CookieRotations()
    tracker.filter('POST','login/index.php',200,'MoodleSession=old',login,now=1)
    assert tracker.filter('GET','lib/ajax/service-nologin.php',200,'MoodleSession=old',late,now=2)==late
