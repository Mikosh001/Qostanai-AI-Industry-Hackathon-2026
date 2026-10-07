"""Session timestamp and legacy database regressions."""
import sqlite3, json
import pytest
from backend.store import Store


def test_actual_start_end_timestamps_survive_restart_and_terminal_replay(tmp_path):
    s=Store(tmp_path/'test.db');item=s.create_session({'moodle':{'nonce':'unique'}});sid=item['id']
    assert item['started'] is None and item['ended'] is None
    s.update_session(sid,patch={'moodle_prepared':True})
    assert s.session(sid)['started'] is None
    active=s.update_session(sid,'active');assert active['started']>=item['created']
    assert s.update_session(sid,'active')['started']==active['started']
    finished=s.update_session(sid,'completed')
    assert finished['ended']>=active['started']
    assert s.update_session(sid,'completed')['ended']==finished['ended']
    with pytest.raises(ValueError):s.update_session(sid,'active')
    s.db.close();s=Store(tmp_path/'test.db')
    assert s.session_by_nonce('unique')['started']==active['started']
    assert s.session(sid)['ended']==finished['ended']


def test_old_database_migrates_without_inventing_start_times(tmp_path):
    path=tmp_path/'old.db';db=sqlite3.connect(path)
    db.execute('CREATE TABLE sessions(id TEXT PRIMARY KEY,created TEXT,ended TEXT,status TEXT,data TEXT)')
    db.executemany('INSERT INTO sessions VALUES(?,?,?,?,?)',[
        ('a','2026-10-06',None,'preflight','{}'),
        ('b','2026-10-06','2026-10-07','completed',json.dumps({'active_started_at':'2026-10-06T12:00:00+00:00'}))])
    db.commit();db.close();s=Store(path)
    assert s.session('a')['started'] is None
    assert s.session('b')['started']=='2026-10-06T12:00:00+00:00'
