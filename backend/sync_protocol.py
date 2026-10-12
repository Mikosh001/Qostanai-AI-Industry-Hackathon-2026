"""Small device-authenticated lease messages, independent of evidence uploads."""
import hashlib
import hmac
import time
import uuid
from .security import canonical


def headers(config, raw):
    key = config.get('device_key') or config.get('pairing_key', '')
    return {'x-sergek-signature': hmac.new(key.encode(), raw, hashlib.sha256).hexdigest(),
            'x-sergek-device': config.get('device_id',''), 'Content-Type':'application/json'}


def lease_packet(store, sid):
    return canonical({'packet_id':uuid.uuid4().hex,'sent_at':time.time(),
                      'session_id':sid,'anchor':store.anchor(sid)})


def acknowledge(store, sid, response):
    anchor=response.get('anchor')
    if anchor is None:
        return  # Compatibility receiver; does not claim an independent receipt.
    events=store.events(sid)
    count=anchor.get('count')
    if isinstance(count,bool) or not isinstance(count,int) or not 0<=count<=len(events):
        raise ValueError('Invalid hub event acknowledgement')
    head=events[count-1]['hash'] if count else '0'*64
    if anchor.get('head')!=head:
        raise ValueError('Hub event head does not match local history')
    old=store.setting('hub_anchor:'+sid,{'count':0})
    if count<old['count']:
        raise ValueError('Hub anchor rolled backwards')
    store.set_setting('hub_anchor:'+sid,anchor)

