"""HTTPS protocol-2 synthetic load. No physical camera, OS guard or PHP load.

Uses independent driver processes and persistent connections. The test owns its
temporary hub, keys and database, and never touches a university or demo session.
"""
import argparse,asyncio,base64,hashlib,hmac,json,os,secrets,socket,subprocess,sys,tempfile,time,uuid,io,zipfile,shutil
from pathlib import Path
from datetime import datetime,timezone
import httpx,numpy as np,psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.store import Store
from backend.security import canonical
from backend.trust import enroll,issue
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

def stamp():return datetime.now(timezone.utc).isoformat()
def stats(values):return {f'p{p}':round(float(np.percentile(values,p)),2) for p in (50,95,99)} if values else {}

async def drive(config,index,workers):
    clients=config['clients'][index::workers]
    result={'lease':[],'status':[],'ingest':[],'server_ms':[],'errors':[],'stale':0,'completed':0,'sizes':[]}
    async with httpx.AsyncClient(verify=config['ca'],timeout=15,trust_env=False,
        limits=httpx.Limits(max_connections=len(clients)*2,max_keepalive_connections=len(clients)*2,keepalive_expiry=30)) as client:
        async def request(phase,path,body=None,device=None,nonce=None):
            t=time.perf_counter()
            try:
                if body is not None:
                    raw=canonical(body)
                    headers={'x-sergek-device':device['device_id'],'x-sergek-signature':hmac.new(device['device_key'].encode(),raw,hashlib.sha256).hexdigest()}
                    response=await client.post(config['url']+path,content=raw,headers=headers)
                    result['sizes'].append(len(raw))
                else:
                    response=await client.get(config['url']+path,params={'nonce':nonce},headers={'x-sergek-moodle':config['moodle_key']})
                result[phase].append((time.perf_counter()-t)*1000)
                if response.headers.get('x-sergek-server-ms'):result['server_ms'].append(float(response.headers['x-sergek-server-ms']))
                if not response.is_success:
                    result['errors'].append({'phase':phase,'status':response.status_code,'detail':response.text[:100]})
                    return {}
                return response.json()
            except Exception as exc:
                result['errors'].append({'phase':phase,'error':type(exc).__name__});return {}

        async def student(entry,number):
            await asyncio.sleep(number*config['ramp']/max(1,len(clients)))
            item=entry['session'];anchor={'count':0,'head':'0'*64}
            events=[]
            for sequence in range(config['events']):
                event={'id':uuid.uuid4().hex,'session_id':item['id'],'created':stamp(),'kind':'phone_detected','detail':{'synthetic':True,'sequence':sequence},'previous_hash':events[-1]['hash'] if events else '0'*64}
                event['hash']=hashlib.sha256(canonical(event)).hexdigest();events.append(event)
            async def ingest(terminal=False,media=False):
                nonlocal anchor
                evidence={}
                if media and config['evidence_bytes']:
                    eid=uuid.uuid4().hex
                    event={'id':eid,'session_id':item['id'],'created':stamp(),'kind':'phone_detected','detail':{'synthetic':True},'previous_hash':events[-1]['hash']}
                    event['hash']=hashlib.sha256(canonical(event)).hexdigest();events.append(event)
                    blob=io.BytesIO()
                    with zipfile.ZipFile(blob,'w') as archive:
                        archive.writestr('camera/0000.jpg',b'\xff\xd8\xff'+b'x'*config['evidence_bytes'])
                        archive.writestr('manifest.json',json.dumps({'event_id':eid,'tracks':{'camera':[{'file':'camera/0000.jpg','time':0}]},'primary':'camera'}))
                    raw=blob.getvalue();evidence[eid]=base64.b64encode(raw).decode()
                    commit={'id':uuid.uuid4().hex,'session_id':item['id'],'created':stamp(),'kind':'evidence_committed','detail':{'event_id':eid,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)},'previous_hash':events[-1]['hash']}
                    commit['hash']=hashlib.sha256(canonical(commit)).hexdigest();events.append(commit)
                packet={'packet_id':uuid.uuid4().hex,'sent_at':time.time(),'launch_token':entry['token'],'session':item,
                    'events':events[anchor['count']:],'evidence':evidence,'cursor':anchor['count'],'cursor_head':anchor['head']}
                state=await request('ingest','/api/hub/ingest',packet,entry)
                if 'anchor' in state:anchor=state['anchor']
                if terminal and state.get('ok'):result['completed']+=1
            await ingest()
            deadline=time.monotonic()+config['duration'];iteration=0
            while time.monotonic()<deadline:
                t=time.monotonic()
                lease={'packet_id':uuid.uuid4().hex,'sent_at':time.time(),'session_id':item['id'],'anchor':anchor}
                state=await request('lease','/api/hub/lease',lease,entry)
                status=await request('status','/api/moodle/status',nonce=item['data']['moodle']['nonce'])
                if state and not state.get('active'):result['stale']+=1
                if status and not status.get('active'):result['stale']+=1
                iteration+=1
                if iteration%15==0:await ingest(media=True)  # Delta only; optional bounded synthetic media burst.
                await asyncio.sleep(max(0,config['period']-(time.monotonic()-t)))
            item.update(status='completed',ended=stamp())
            await ingest(True)
        await asyncio.gather(*(student(entry,i) for i,entry in enumerate(clients)))
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--students',type=int,default=200);parser.add_argument('--duration',type=int,default=120)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--events',type=int,default=100)
    parser.add_argument('--evidence-bytes',type=int,default=0)
    parser.add_argument('--period',type=float,default=2);parser.add_argument('--ramp',type=float,default=8)
    parser.add_argument('--lab',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--worker',type=int);parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    if args.worker is not None:
        result=asyncio.run(drive(json.loads(args.config.read_text()),args.worker,args.workers))
        args.output.write_text(json.dumps(result));return
    if not args.lab or not args.output:parser.error('--lab and --output are required')
    if min(args.students,args.duration,args.workers,args.events)<1 or args.period<.5 or not 0<=args.evidence_bytes<=1_900_000:parser.error('Invalid load parameters')
    estimated=args.students*(args.duration//30+1)*args.evidence_bytes
    if shutil.disk_usage(tempfile.gettempdir()).free<estimated*1.5+2*1024**3:
        parser.error('Insufficient disk for this synthetic media volume plus database/recovery reserve; reduce duration/students/evidence size')
    with tempfile.TemporaryDirectory(prefix='sergek-soak-') as folder:
        backend_hash=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'backend').glob('*.py')))).hexdigest()
        driver_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        data=Path(folder);store=Store(data/'sergek.db');private=Ed25519PrivateKey.generate()
        store.set_setting('moodle_public_key',private.public_key().public_bytes_raw().hex())
        moodle_key=secrets.token_urlsafe(48);store.set_secret('moodle_key',moodle_key)
        config={'clients':[],'duration':args.duration,'events':args.events,'period':args.period,'ramp':args.ramp,'evidence_bytes':args.evidence_bytes,
                'moodle_key':moodle_key,'ca':str((args.lab/'localhost.crt').resolve())}
        for i in range(args.students):
            device=enroll(store,'Synthetic '+str(i));now=time.time()
            claims={'aud':'sergek-exam-v2','iat':now,'exp':now+1800,'nonce':uuid.uuid4().hex,'userid':str(i+1),
                'quizid':'17','url':'https://localhost/mod/quiz/view.php?id=100','mode':'strict','device_id':device['device_id']}
            raw=base64.urlsafe_b64encode(canonical(claims)).decode().rstrip('=')
            token='SG2.'+raw+'.'+base64.urlsafe_b64encode(private.sign(raw.encode())).decode().rstrip('=')
            issue(store,token);created=stamp()
            item={'id':uuid.uuid4().hex,'created':created,'started':created,'ended':None,'status':'active',
                'data':{'student':'Synthetic '+str(i),'exam':'Load fixture','platform':'moodle','mode':'strict','exam_url':claims['url'],'moodle':claims}}
            config['clients'].append({**device,'token':token,'session':item})
        store.db.close()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config['url']=f'https://127.0.0.1:{port}'
        cfg=data/'drivers.json';cfg.write_text(json.dumps(config))
        log=(data/'hub.log').open('wb')
        server=subprocess.Popen([sys._base_executable,str(ROOT/'lab/runtime.py'),sys.executable,'--module','backend.run','--port',str(port),'--cert',str((args.lab/'localhost.crt').resolve()),'--key',str((args.lab/'localhost.key').resolve())],cwd=ROOT,
            env={**os.environ,'SERGEK_DATA':str(data),'SERGEK_SERVICE_ROLE':'hub','SERGEK_DEMO_CONFIG':'','SERGEK_METRICS':'1'},stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        drivers=[];rss=[];began=time.perf_counter()
        try:
            for _ in range(100):
                try:
                    if httpx.get(config['url']+'/api/health',verify=config['ca'],timeout=1,trust_env=False).is_success:break
                except httpx.HTTPError:time.sleep(.1)
            else:raise RuntimeError('Isolated hub did not start')
            for i in range(args.workers):
                drivers.append(subprocess.Popen([sys.executable,__file__,'--worker',str(i),'--workers',str(args.workers),'--config',str(cfg),'--output',str(data/f'driver-{i}.json')],stdout=subprocess.DEVNULL,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
            while any(d.poll() is None for d in drivers):
                if server.poll() is not None:raise RuntimeError('Hub crashed')
                parent=psutil.Process(server.pid)
                rss.append(sum(p.memory_info().rss for p in [parent,*parent.children(recursive=True)] if p.is_running())/1024**2)
                time.sleep(1)
            if any(d.returncode for d in drivers):raise RuntimeError('Load driver failed')
            results=[json.loads((data/f'driver-{i}.json').read_text()) for i in range(args.workers)]
            report={'date':'2026-10-12','scope':__doc__,'students':args.students,'duration_per_client_seconds':args.duration,
              'elapsed_seconds':round(time.perf_counter()-began,2),'drivers':args.workers,'initial_events_per_session':args.events,
              'lease_period_seconds':args.period,'ramp_seconds':args.ramp,'errors':[e for r in results for e in r['errors']],
              'synthetic_evidence_bytes_per_30_seconds':args.evidence_bytes,
              'backend_sha256':backend_hash,
              'driver_sha256':driver_hash,
              'stale':sum(r['stale'] for r in results),'completed':sum(r['completed'] for r in results),
              'hub_rss_mb':{'first':round(rss[0],1),'peak':round(max(rss),1),'last':round(rss[-1],1)},
              'requests':{k:len([v for r in results for v in r[k]]) for k in ('ingest','lease','status')},
              'latency_ms':{k:stats([v for r in results for v in r[k]]) for k in ('ingest','lease','status')},
              'server_processing_ms':stats([v for r in results for v in r['server_ms']]),
              'machine':{'logical_cpus':psutil.cpu_count(),'ram_gb':round(psutil.virtual_memory().total/1024**3,1)}}
            verify=Store(data/'sergek.db')
            report['persisted_completed']=verify.db.execute("SELECT count(*) FROM sessions WHERE status='completed' AND started IS NOT NULL AND ended IS NOT NULL").fetchone()[0]
            report['integrity_failures']=sum(not verify.integrity(s['id']) for s in verify.sessions());verify.db.close()
            report['passed']=not report['errors'] and report['stale']==0 and report['completed']==args.students and report['persisted_completed']==args.students and report['integrity_failures']==0 and report['latency_ms']['lease'].get('p95',float('inf'))<=2000
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2));print(json.dumps({**report,'errors':{'count':len(report['errors']),'first':report['errors'][:5]}}))
        finally:
            for driver in drivers:
                if driver.poll() is None:driver.terminate();driver.wait(timeout=10)
            server.terminate();server.wait(timeout=15);log.close()

if __name__=='__main__':main()
