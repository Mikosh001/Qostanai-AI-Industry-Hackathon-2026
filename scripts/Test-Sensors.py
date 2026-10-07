"""Physical sensor preflight, RAM only: no enrolled identity, stored media or OS restrictions."""
import argparse, json, statistics, sys, tempfile, time
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from backend.engine import Engine
from backend.store import Store
from backend.config import Policy, MODELS

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds',type=int,default=30,choices=range(15,121))
parser.add_argument('--output',type=Path,default=Path('tests/hardware-smoke.json'))
args=parser.parse_args()
with tempfile.TemporaryDirectory(prefix='sergek-sensor-') as directory:
    data=Path(directory);store=Store(data/'db.sqlite');engine=Engine(store,MODELS,data,bytes(32))
    samples=[]
    try:
        deadline=time.monotonic()+45
        while engine.loading and time.monotonic()<deadline:time.sleep(.1)
        if not engine.status()['models_ready']:raise RuntimeError(engine.load_error or 'Models not ready')
        sid=store.create_session({'student':'Sensor fixture','exam':'Preflight only'})['id']
        engine.start_camera(sid,0,Policy())
        engine.start_recording()
        # Measure steady capture, keeping cold camera start out of FPS statistics.
        deadline=time.monotonic()+15
        while engine.status()['fps'] == 0 and time.monotonic()<deadline:time.sleep(.1)
        if engine.status()['fps'] == 0:raise RuntimeError('Camera produced no measured frame rate')
        for _ in range(args.seconds):time.sleep(1);samples.append(engine.status())
    finally:
        engine.stop_camera();engine.writer.shutdown();store.db.close()
    error_keys=['camera_error','microphone_error','screen_error','evidence_error']
    errors={key:next((sample.get(key) for sample in samples if sample.get(key)),'') for key in error_keys}
    report={'date':str(date.today()),'scope':__doc__,'passed':bool(samples) and all(sample['camera_running'] and sample['microphone_running'] and sample['screen_recording'] for sample in samples) and not any(errors.values()),
        'capture_fps_median':statistics.median(sample['fps'] for sample in samples),
        'capture_fps_min':min(sample['fps'] for sample in samples),
        'analysis_fps_median':statistics.median(sample['analysis_fps'] for sample in samples),
        'screen_fps_median':statistics.median(sample['screen_fps'] for sample in samples),
        'audio_dropouts':max(sample.get('audio_dropouts',0) for sample in samples),'errors':errors,
        'seconds':args.seconds,'capture_threads_stopped':not engine.status()['camera_running']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));sys.exit(0 if report['passed'] else 1)
