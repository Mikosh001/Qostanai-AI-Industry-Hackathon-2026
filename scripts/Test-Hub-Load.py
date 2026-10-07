"""Actual isolated HTTPS hub with synthetic students; no cameras or OS enforcement."""
import argparse, asyncio, base64, hashlib, hmac, json, os, secrets, socket, subprocess, sys, tempfile, time, uuid
from pathlib import Path
from datetime import datetime, timezone
import httpx, numpy as np, cv2, psutil
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from backend.store import Store
from backend.security import canonical
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--students',type=int,default=200);parser.add_argument('--rounds',type=int,default=12)
parser.add_argument('--lab',type=Path,required=True);parser.add_argument('--output',type=Path,default=Path('tests/hub-load-v140.json'))
args=parser.parse_args();key=secrets.token_hex(32);moodle_key=secrets.token_hex(32)
latencies=[];status_latency=[];errors=[];stale=[];rss=[];sizes=[]
def utc():return datetime.now(timezone.utc).isoformat()
def percentile(values,p):return round(float(np.percentile(values,p)),1) if values else None

async def run(port):
    stamp=utc();students=[]
    for i in range(args.students):
        students.append({'id':uuid.uuid4().hex,'created':stamp,'started':stamp,'ended':None,'status':'active',
             'data':{'student':'Load '+str(i),'exam':'Synthetic load','platform':'moodle','mode':'strict',
                     'active_started_at':stamp,'moodle':{'nonce':secrets.token_hex(24)}}})
    _,jpeg=cv2.imencode('.jpg',np.random.default_rng(1).integers(0,256,(240,320,3),dtype=np.uint8))
    # Real JPEG reference on first packet, plus one encrypted evidence clip per client.
    reference={'photo':'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode(),'model':'Load fixture'}
    events={}
    for item in students:
        e={'id':uuid.uuid4().hex,'session_id':item['id'],'created':stamp,'kind':'phone_detected',
           'detail':{'fixture':True},'previous_hash':'0'*64}
        e['hash']=hashlib.sha256(canonical(e)).hexdigest();e.update(media=None,verdict='pending',note='');events[item['id']]=e
    start=time.perf_counter();round_gaps=[]
    async with httpx.AsyncClient(verify=str(args.lab/'localhost.crt'),timeout=25,
             limits=httpx.Limits(max_connections=args.students,max_keepalive_connections=args.students)) as client:
        async def send(item,iteration):
            packet={'packet_id':uuid.uuid4().hex,'sent_at':time.time(),'session':item,
                    'events':[events[item['id']]],'evidence':{}}
            if iteration==0:
                packet['reference']=reference
                packet['evidence']={events[item['id']]['id']:base64.b64encode(json.dumps({'camera':[],'fixture':True}).encode()).decode()}
            raw=canonical(packet);sizes.append(len(raw));t=time.perf_counter()
            try:
                r=await client.post(f'https://localhost:{port}/api/hub/ingest',content=raw,
                   headers={'x-sergek-signature':hmac.new(key.encode(),raw,hashlib.sha256).hexdigest()})
                latencies.append((time.perf_counter()-t)*1000)
                if r.status_code!=200:errors.append({'phase':'ingest','status':r.status_code,'body':r.text[:100]})
            except Exception as e:errors.append({'phase':'ingest','error':type(e).__name__})
        async def probe(item):
            t=time.perf_counter()
            try:
                r=await client.get(f'https://localhost:{port}/api/moodle/status',params={'nonce':item['data']['moodle']['nonce']},headers={'x-sergek-moodle':moodle_key})
                status_latency.append((time.perf_counter()-t)*1000)
                if r.status_code!=200:errors.append({'phase':'status','status':r.status_code})
                elif not r.json().get('active'):stale.append(item['id'])
            except Exception as e:errors.append({'phase':'status','error':type(e).__name__})
        for iteration in range(args.rounds):
            cycle=time.perf_counter()
            await asyncio.gather(*(send(item,iteration) for item in students))
            await asyncio.gather(*(probe(item) for item in students))
            round_gaps.append(round(time.perf_counter()-cycle,3))
            parent=psutil.Process(process.pid)
            rss.append(sum(p.memory_info().rss for p in [parent,*parent.children(recursive=True)] if p.is_running()))
            print(json.dumps({'round':iteration+1,'seconds':round_gaps[-1],'errors':len(errors),'stale':len(stale)}),flush=True)
            await asyncio.sleep(max(0,5-(time.perf_counter()-cycle)))
        # Every student's terminal timestamp must survive a signed finish packet.
        for item in students:item.update(status='completed',ended=utc())
        await asyncio.gather(*(send(item,args.rounds) for item in students))
    elapsed=time.perf_counter()-start
    return {'scope':__doc__,'students':args.students,'heartbeat_period_seconds':5,'rounds':args.rounds,
       'duration_seconds':round(elapsed,2),'ingest_requests':len(latencies),'status_requests':len(status_latency),
       'ingest_ms':{p:percentile(latencies,int(p[1:])) for p in ('p50','p95','p99')},
       'status_ms':{p:percentile(status_latency,int(p[1:])) for p in ('p50','p95','p99')},
       'errors':errors,'stale_active_responses':len(stale),'max_cycle_seconds':max(round_gaps),
       'payload_max_bytes':max(sizes),'hub_rss_peak_mb':round(max(rss)/1024**2,1),
       'passed':not errors and not stale and max(round_gaps)<15,
       'machine':{'logical_cpus':psutil.cpu_count(),'ram_gb':round(psutil.virtual_memory().total/1024**3,1)}}

with tempfile.TemporaryDirectory(prefix='sergek-load-') as folder:
    data=Path(folder);s=Store(data/'sergek.db');s.set_setting('hub_receive_key',key);s.set_setting('moodle_key',moodle_key);s.db.close()
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    with (data/'backend.log').open('wb') as log:
        process=subprocess.Popen([sys.executable,'-m','backend.run','--port',str(port),'--cert',str(args.lab/'localhost.crt'),'--key',str(args.lab/'localhost.key')],cwd=ROOT,
            env={**os.environ,'SERGEK_DATA':str(data),'SERGEK_DEMO_CONFIG':''},stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                try:
                    if httpx.get(f'https://localhost:{port}/api/health',verify=str(args.lab/'localhost.crt'),timeout=1).is_success:break
                except httpx.HTTPError:time.sleep(.1)
            report=asyncio.run(run(port))
            s=Store(data/'sergek.db');report['completed_sessions']=s.db.execute("SELECT count(*) FROM sessions WHERE status='completed' AND started IS NOT NULL AND ended IS NOT NULL").fetchone()[0];s.db.close()
            report['passed'] &= report['completed_sessions']==args.students
            args.output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report));sys.exit(0 if report['passed'] else 1)
        finally:process.terminate();process.wait(timeout=15)
