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
parser.add_argument('--events',type=int,default=1,help='Full event history in every snapshot')
parser.add_argument('--probe-during-ingest',action='store_true',help='Probe established sessions while ingest writes are in flight')
parser.add_argument('--independent-clients',action='store_true',help='Each student schedules its own heartbeat without a global round barrier')
parser.add_argument('--backend-root',type=Path,help='Compare another checkout with exactly the same client driver')
parser.add_argument('--hostname',default='127.0.0.1',help='Use a certificate covering this hostname/IP')
parser.add_argument('--no-media',action='store_true',help='Isolate metadata load from reference/evidence filesystem writes')
parser.add_argument('--timing-wrapper',type=Path,help='Optional isolated audit server exposing server-side timings')
parser.add_argument('--lab',type=Path,required=True);parser.add_argument('--output',type=Path,default=Path('tests/hub-load-v140.json'))
args=parser.parse_args();key=secrets.token_hex(32);moodle_key=secrets.token_hex(32)
if args.backend_root:ROOT=args.backend_root.resolve()
if min(args.students,args.rounds,args.events)<1:parser.error('students, rounds and events must be positive')
latencies=[];status_latency=[];errors=[];stale=[];rss=[];sizes=[]
server_latencies=[];server_status_latencies=[]
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
        chain=[];previous='0'*64
        for sequence in range(args.events):
            e={'id':uuid.uuid4().hex,'session_id':item['id'],'created':stamp,'kind':'phone_detected',
               'detail':{'fixture':True,'sequence':sequence},'previous_hash':previous}
            e['hash']=hashlib.sha256(canonical(e)).hexdigest();previous=e['hash']
            e.update(media=None,verdict='pending',note='');chain.append(e)
        events[item['id']]=chain
    start=time.perf_counter();round_gaps=[]
    async with httpx.AsyncClient(verify=str(args.lab/'localhost.crt'),timeout=25,
             limits=httpx.Limits(max_connections=2*args.students,max_keepalive_connections=2*args.students,keepalive_expiry=30)) as client:
        async def send(item,iteration):
            packet={'packet_id':uuid.uuid4().hex,'sent_at':time.time(),'session':item,
                    'events':events[item['id']],'evidence':{}}
            if iteration==0 and not args.no_media:
                packet['reference']=reference
                packet['evidence']={events[item['id']][0]['id']:base64.b64encode(json.dumps({'camera':[],'fixture':True}).encode()).decode()}
            raw=canonical(packet);sizes.append(len(raw));t=time.perf_counter()
            try:
                r=await client.post(f'https://{args.hostname}:{port}/api/hub/ingest',content=raw,
                   headers={'x-sergek-signature':hmac.new(key.encode(),raw,hashlib.sha256).hexdigest()})
                latencies.append((time.perf_counter()-t)*1000)
                if r.headers.get('x-audit-server-ms'):server_latencies.append(float(r.headers['x-audit-server-ms']))
                if r.status_code!=200:errors.append({'phase':'ingest','status':r.status_code,'body':r.text[:100]})
            except Exception as e:errors.append({'phase':'ingest','error':type(e).__name__})
        async def probe(item):
            t=time.perf_counter()
            try:
                r=await client.get(f'https://{args.hostname}:{port}/api/moodle/status',params={'nonce':item['data']['moodle']['nonce']},headers={'x-sergek-moodle':moodle_key})
                status_latency.append((time.perf_counter()-t)*1000)
                if r.headers.get('x-audit-server-ms'):server_status_latencies.append(float(r.headers['x-audit-server-ms']))
                if r.status_code!=200:errors.append({'phase':'status','status':r.status_code})
                elif not r.json().get('active'):stale.append(item['id'])
            except Exception as e:errors.append({'phase':'status','error':type(e).__name__})
        async def independent_student(item):
            for iteration in range(args.rounds):
                cycle=time.perf_counter()
                if iteration == 0:
                    await send(item,iteration)
                    await probe(item)
                else:
                    await asyncio.gather(send(item,iteration),probe(item))
                round_gaps.append(round(time.perf_counter()-cycle,3))
                await asyncio.sleep(max(0,5-(time.perf_counter()-cycle)))
        if args.independent_clients:
            await asyncio.gather(*(independent_student(item) for item in students))
            parent=psutil.Process(process.pid)
            rss.append(sum(p.memory_info().rss for p in [parent,*parent.children(recursive=True)] if p.is_running()))
        for iteration in ([] if args.independent_clients else range(args.rounds)):
            cycle=time.perf_counter()
            if args.probe_during_ingest and iteration > 0:
                await asyncio.gather(*(send(item,iteration) for item in students),*(probe(item) for item in students))
            else:
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
    return {'scope':__doc__,'students':args.students,'events_per_student':args.events,'concurrent_probes':args.probe_during_ingest,'independent_clients':args.independent_clients,'hostname':args.hostname,'media_included':not args.no_media,'heartbeat_period_seconds':5,'rounds':args.rounds,
       'duration_seconds':round(elapsed,2),'ingest_requests':len(latencies),'status_requests':len(status_latency),
       'ingest_ms':{p:percentile(latencies,int(p[1:])) for p in ('p50','p95','p99')},
       'status_ms':{p:percentile(status_latency,int(p[1:])) for p in ('p50','p95','p99')},
       'server_ingest_ms':{p:percentile(server_latencies,int(p[1:])) for p in ('p50','p95','p99')},
       'server_status_ms':{p:percentile(server_status_latencies,int(p[1:])) for p in ('p50','p95','p99')},
       'errors':errors,'stale_active_responses':len(stale),'max_cycle_seconds':max(round_gaps),
       'payload_max_bytes':max(sizes),'hub_rss_peak_mb':round(max(rss)/1024**2,1),
       'passed':not errors and not stale and max(round_gaps)<15,
       'machine':{'logical_cpus':psutil.cpu_count(),'ram_gb':round(psutil.virtual_memory().total/1024**3,1)}}

with tempfile.TemporaryDirectory(prefix='sergek-load-') as folder:
    data=Path(folder);s=Store(data/'sergek.db');s.set_setting('hub_receive_key',key);s.set_setting('moodle_key',moodle_key);s.db.close()
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    with (data/'backend.log').open('wb') as log:
        entry=[str(args.timing_wrapper.resolve())] if args.timing_wrapper else ['-m','backend.run']
        process=subprocess.Popen([sys.executable,*entry,'--port',str(port),'--cert',str(args.lab/'localhost.crt'),'--key',str(args.lab/'localhost.key')],cwd=ROOT,
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
        finally:
            # Windows venv python.exe is a launcher. Terminating only that PID
            # leaves the real backend child running and locks the temporary DB/log.
            try:owned=psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:owned=[]
            for child in owned:
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            if process.poll() is None:process.terminate()
            _,alive=psutil.wait_procs(owned,timeout=10)
            for child in alive:
                try:child.kill()
                except psutil.NoSuchProcess:pass
            process.wait(timeout=15)
