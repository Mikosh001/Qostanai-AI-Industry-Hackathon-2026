"""One duration schedule shared by capture, live feedback and human review."""
import math

SCALE = 'review-priority/2'
TIERS = {
    'phone': ((0, 5), (2, 10), (5, 15), (10, 20)),
    'multiple_faces': ((3, 2),),
    'identity_mismatch': ((3, 10), (5, 15)),
    'gaze': ((5, 3), (10, 5), (20, 10)),
    'audio': ((0, 1),),
}
FAMILIES = {
    'phone_brief': 'phone', 'phone_detected': 'phone', 'phone_raised': 'phone',
    'gaze_side': 'gaze', 'gaze_down': 'gaze',
    'sound_activity': 'audio', 'sustained_noise': 'audio',
}
OTHER_WEIGHTS = {'face_absent':12,'camera_obscured':12,'presentation_attack':25,
                 'foreground_changed':20,'remote_control':45,'forbidden_process':30}

def family(kind):
    return FAMILIES.get(kind,kind)

def family_kinds(kind):
    group=family(kind)
    return {k for k,v in FAMILIES.items() if v==group} or {kind}

def duration_points(kind, duration):
    return max((points for threshold,points in TIERS.get(family(kind),()) if duration>=threshold),default=0)

def next_stage(kind, duration):
    return next((threshold for threshold,_ in TIERS.get(family(kind),()) if threshold>duration),None)

def event_points(event):
    kind=event['kind'];detail=event.get('detail') or {}
    if family(kind) not in TIERS:return OTHER_WEIGHTS.get(kind,10)
    fallback=2 if kind in {'phone_detected','phone_raised'} else 0
    value=detail.get('duration_seconds',detail.get('noise_seconds',fallback))
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):value=0
    return duration_points(kind,max(0,value))

def episode_key(event):
    episode=(event.get('detail') or {}).get('episode_id')
    return (family(event['kind']),episode) if isinstance(episode,str) and 0<len(episode)<=128 else ('event',event['id'])
