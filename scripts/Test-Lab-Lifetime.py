import sys,time,json,ssl,httpx,psutil
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root/'lab'))
from independent import start_independent,process_in_job
python=(root/'../../work/sergek-venv/Scripts/python.exe').resolve()
pid=start_independent([sys._base_executable,str(root/'lab/runtime.py'),str(python),str(root/'lab/start.py')],root,hidden=True)
print('Independent lab setup PID:',pid,flush=True)
lab=(root/'../../work/local-moodle').resolve()
for i in range(60):
 if not psutil.pid_exists(pid): break
 time.sleep(1)
assert not psutil.pid_exists(pid),'Setup did not terminate'
time.sleep(12)
results={}
with httpx.Client(verify=ssl.create_default_context(cafile=str(lab/'localhost.crt')),timeout=4) as c:
 for name,url in [('hub','https://localhost:9443/api/health'),('moodle','https://localhost/login/index.php')]:
  r=c.get(url);r.raise_for_status();results[name+'_http_status']=r.status_code
for name,pid in json.loads((lab/'pids.json').read_text()).items():
 p=psutil.Process(pid);assert p.is_running()
 attached=process_in_job(pid)
 if name in ('tls','hub'): assert not attached,(name,pid)
 results[name]={'pid':pid,'alive_after_setup_exit':True,'in_job':attached,'runtime':p.name()}
(root/'tests/lab-lifetime-v142.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps(results),flush=True)
