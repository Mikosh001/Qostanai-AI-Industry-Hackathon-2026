"""Reproducible labelled-image checks; not webcam accuracy or physical replay proof."""
import argparse, json, time, sys, hashlib
from pathlib import Path
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from backend.vision import Vision
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dataset',type=Path,required=True)
parser.add_argument('--spoof-fixtures',type=Path,required=True)
parser.add_argument('--output',type=Path,default=Path('tests/vision-v140.json'))
args=parser.parse_args();root=Path(__file__).resolve().parent.parent
v=Vision(root/'models');assert v.ready,v.error
records=[];spoof=[]
try:
    for lab in sorted((args.dataset/'labels/train2017').glob('*.txt')):
        file=args.dataset/'images/train2017'/(lab.stem+'.jpg');frame=cv2.imread(str(file))
        if frame is None:continue
        label=any(s.startswith('67 ') for s in lab.read_text().splitlines())
        v.phone_sample_at=0;v.phone_crop_cycle=0
        boxes=v.phones(frame)
        # Test both detail views, as the live stream alternates between them.
        v.phone_sample_at=0;boxes=boxes+v.phones(frame)
        records.append({'file':file.name,'label':label,'detected':bool(boxes),'score':round(max((p['confidence'] for p in boxes),default=0),4)})
    for file in sorted(args.spoof_fixtures.glob('image_*.jpg')):
        frame=cv2.imread(str(file));v.presentation.last_at=0
        signal,_=v.analyze(frame)
        spoof.append({'file':file.name,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
            'expected':'live' if '_T' in file.name else 'spoof','faces':signal['faces'],'presentation':signal.get('presentation')})
finally:v.close()
pos=[r for r in records if r['label']];neg=[r for r in records if not r['label']]
report={'scope':__doc__,'phone_threshold':v.phone_threshold,'phone_model':v.model_name,
    'phone_positive_images':len(pos),'positive_detected':sum(r['detected'] for r in pos),
    'phone_negative_images':len(neg),'negative_false_detections':sum(r['detected'] for r in neg),
    'positives':pos,'false_detections':[r for r in neg if r['detected']],
    'missing_dataset_images':128-len(records),
    'spoof_source':'https://github.com/yakhyo/face-anti-spoofing/tree/main/assets','spoof_images':spoof}
args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
