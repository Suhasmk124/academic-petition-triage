"""Controlled deployed stub outage, circuit recovery and Redis rate-limit checks."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]


def main():
    docker=shutil.which('docker') or r'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    env=dict(os.environ,TRIAGE_CACHE_TTL='0',TRIAGE_RATE_LIMIT='0')
    def compose(*args,environment=env):
        subprocess.run([docker,'compose',*args],cwd=ROOT,env=environment,check=True)
    def ready():
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try:
                if httpx.get('http://127.0.0.1:8000/ready',timeout=3).status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(1)
        raise RuntimeError('Deployment readiness deadline exceeded')
    key=(ROOT/'.secrets/triage_key').read_text().strip()
    evidence=[]
    try:
        compose('up','-d','--no-deps','--scale','worker=1','--force-recreate','api','worker')
        ready()
        with httpx.Client(base_url='http://127.0.0.1:8000',headers={'Authorization':'Bearer '+key},timeout=10) as client:
            def submit():
                response=client.post('/petitions',json={'petition':'Synthetic outage test: what attendance condonation rules apply?','synthetic':True})
                assert response.status_code==202,response.status_code
                deadline=time.monotonic()+150
                while time.monotonic()<deadline:
                    run=client.get(response.json()['poll_url']).json()
                    if run['status'] in ('SUCCEEDED','FAILED'):break
                    time.sleep(.2)
                assert run['status']=='SUCCEEDED',run
                result=run['result']
                assert result['safety']['output']=='passed' and not result['final_decision_made']
                assert not result['cache']['hit']
                evidence.append(dict(run_id=run['run_id'],reliability=result['reliability']))
                return result
            compose('stop','stub')
            for _ in range(3):
                assert submit()['reliability']['reason']=='STUB_UNAVAILABLE'
            assert submit()['reliability']['reason']=='CIRCUIT_OPEN'
            compose('start','stub')
            time.sleep(31)
            deadline=time.monotonic()+150
            while time.monotonic()<deadline:
                state=subprocess.check_output([docker,'compose','ps','--format','json','stub'],cwd=ROOT).decode()
                if 'healthy' in state and 'unhealthy' not in state:break
                time.sleep(2)
            else:raise RuntimeError('Stub did not recover')
            assert submit()['reliability']['fallback'] is False
            limited=dict(env,TRIAGE_RATE_LIMIT='2')
            compose('up','-d','--no-deps','--force-recreate','api',environment=limited)
            ready()
            statuses=[client.post('/petitions',json={'petition':'Synthetic rate limit test: attendance rules?','synthetic':True}).status_code for _ in range(3)]
            assert statuses==[202,202,429],statuses
        report=dict(passed=True,deployment='Docker Compose',stub_outage=evidence,
                    rate_limit_statuses=statuses,cache_disabled=True,hosted_requests=0)
        (ROOT/'evaluations/deployed_failures.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('PASS: real stub outage, circuit opening, recovery and shared rate limiting.')
    finally:
        compose('up','-d','--scale','worker=3','--force-recreate','api','worker',environment=dict(os.environ))


if __name__=='__main__':main()
