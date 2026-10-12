"""Evaluate human-verified phone intervals in private, previously unseen videos.

Manifest: {"annotation_verified":true,"videos":[{"file":"clip.mp4",
"phone_intervals":[{"start":5,"end":15,"group":"back/center"}]}]}.
Unlabelled time is negative; verify the entire video before setting the flag.
No camera is opened and no footage leaves the computer.
"""
import argparse,json,sys,hashlib,math,time
from pathlib import Path
import cv2
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.vision import Vision,TemporalRules
from backend.config import Policy


def evaluate(manifest,models):
    value=json.loads(manifest.read_text(encoding='utf-8'))
    if value.get('annotation_verified') is not True:raise ValueError('A human must verify all positive and negative intervals first')
    vision=Vision(models)
    if not vision.ready:raise RuntimeError(vision.error)
    rows=[];tp=fp=fn=tn=0;negative_seconds=0;false_events=0;groups={}
    try:
        for entry in value['videos']:
            path=(manifest.parent/entry['file']).resolve();cap=cv2.VideoCapture(str(path))
            fps=cap.get(cv2.CAP_PROP_FPS);count=cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if not cap.isOpened() or fps<=0 or count<=0:raise ValueError('Unreadable video: '+str(path))
            frame_times=entry.get('frame_times');duration=frame_times[-1]+1/fps if frame_times else count/fps
            intervals=entry['phone_intervals'];ignored=entry.get('ignore_intervals',[]);rules=TemporalRules();flags=[];samples=[]
            for interval in intervals:
                if not 0<=interval['start']<interval['end']<=duration:raise ValueError('Invalid annotation interval')
                if any(interval is not other and interval['start']<other['end'] and other['start']<interval['end'] for other in intervals):raise ValueError('Overlapping annotation intervals')
            index=0;next_sample=0
            while True:
                okay,frame=cap.read()
                if not okay:break
                stamp=frame_times[index] if frame_times else index/fps;index+=1
                if stamp<next_sample:continue
                next_sample+=.5
                vision.phone_sample_at=0  # Offline time, each sampled frame is fresh.
                phones=vision.phones(frame);positive=any(p['start']<=stamp<p['end'] for p in intervals)
                ignore=any(p['start']<=stamp<p['end'] for p in ignored)
                detected=bool(phones)
                if not ignore:
                    tp+=positive and detected;fn+=positive and not detected;fp+=not positive and detected;tn+=not positive and not detected
                    if not positive:negative_seconds+=min(.5,duration-stamp)
                emitted=rules.update_phone({'phone':detected,'phone_sample_at':stamp,'phones':phones},Policy(),stamp)
                if emitted:
                    flags.append(stamp)
                    if not positive and not ignore:false_events+=1
                samples.append({'time':round(stamp,3),'label':positive,'ignored':ignore,'detected':detected,'score':round(max((p['confidence'] for p in phones),default=0),4)})
            cap.release()
            for interval in intervals:
                group=groups.setdefault(interval.get('group','unspecified'),{'episodes':0,'detected_episodes':0})
                group['episodes']+=1
                group['detected_episodes']+=any(interval['start']<=t<interval['end'] for t in flags)
            rows.append({'file':entry['file'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'duration':duration,'event_times':flags,'samples':samples})
    finally:vision.close()
    hours=negative_seconds/3600
    return {'scope':'Offline labelled video, frozen production detector and temporal rule; no OS/Moodle acceptance or population accuracy claim',
            'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'model_sha256':hashlib.sha256((models/vision.model_name).read_bytes()).hexdigest(),
            'sample_fps':2,'threshold':vision.phone_threshold,'sample_confusion':{'tp':tp,'fp':fp,'fn':fn,'tn':tn},
            'sample_precision':tp/(tp+fp) if tp+fp else None,'sample_recall':tp/(tp+fn) if tp+fn else None,
            'negative_hours':hours,'false_events':false_events,'false_events_per_hour':false_events/hours if hours else None,
            'zero_false_events_95_percent_upper_per_hour':-math.log(.05)/hours if hours and not false_events else None,
            'groups':groups,'videos':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('manifest',type=Path);parser.add_argument('--models',type=Path,default=ROOT/'models');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=evaluate(args.manifest,args.models);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='videos'},ensure_ascii=False))
