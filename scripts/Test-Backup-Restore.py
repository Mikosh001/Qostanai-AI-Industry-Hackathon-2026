"""Isolated, offline whole-data backup/restore under the same Windows account.

Does not touch a running lab. Does not claim cross-account DPAPI recovery.
"""
import json,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.store import Store
from backend.security import load_key,encrypt,decrypt
from backend.signed_export import sign_report,public_key,verify_report

with tempfile.TemporaryDirectory(prefix='sergek-backup-qa-') as folder:
    base=Path(folder);source=base/'original';target=base/'restored'
    store=Store(source/'sergek.db')
    store.set_secret('device:fixture','isolated-test-secret')
    item=store.create_session({'student':'Backup fixture','exam':'Recovery'})
    item=store.update_session(item['id'],'active')
    store.add_event(item['id'],'phone_detected',{'fixture':True})
    item=store.update_session(item['id'],'completed')
    anchor=store.anchor(item['id']);trusted=public_key(store)
    signed=sign_report(store,{'session':item,'anchor':anchor})
    key=load_key(source/'media.key');(source/'evidence').mkdir()
    (source/'evidence'/'fixture.sg').write_bytes(encrypt(b'private fixture only',key))
    store.db.close()  # Consistent offline snapshot, including keys, not a live DB copy.
    shutil.copytree(source,target)
    restored=Store(target/'sergek.db');after=restored.session(item['id'])
    assert restored.secret('device:fixture')=='isolated-test-secret'
    assert after['started']==item['started'] and after['ended']==item['ended']
    assert after['status']=='completed' and restored.integrity(item['id'])
    assert restored.anchor(item['id'])==anchor
    assert public_key(restored)==trusted
    assert verify_report(signed,trusted)['anchor']==anchor
    assert decrypt((target/'evidence'/'fixture.sg').read_bytes(),load_key(target/'media.key'))==b'private fixture only'
    restored.db.close()
    print(json.dumps({'passed':True,'scope':'offline whole directory, same Windows account; no cross-user/VM DPAPI claim','timestamps':True,'encrypted_secret':True,'encrypted_media':True,'chain_and_anchor':True,'report_trusted_key':True}))
