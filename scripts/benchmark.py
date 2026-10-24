"""Reproducible Compose/Locust scaling + cache experiment; reports failures honestly."""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=60)
    args = parser.parse_args()
    docker = 'docker'
    if os.name=='nt' and not __import__('shutil').which(docker): docker=r'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    def command(arguments,env=None,check=True):
        return subprocess.run([docker,'compose',*arguments],cwd=ROOT,env=env,check=check)
    slo = json.loads((ROOT/'load/slo.json').read_text())
    rows = []
    for workers,cache in [(1,0),(3,0),(3,300)]:
        env = dict(os.environ,TRIAGE_CACHE_TTL=str(cache),TRIAGE_RATE_LIMIT='0')
        command(['up','-d','--no-deps','--scale',f'worker={workers}','--force-recreate','api','worker'],env)
        deadline = time.monotonic()+180
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=3) as response:
                    if response.status==200: break
            except Exception: time.sleep(1)
        else: raise RuntimeError('Workers not ready')
        # Warm the complete path, including source verification, before measuring.
        key = (ROOT/'.secrets/triage_key').read_text().strip()
        request = urllib.request.Request('http://127.0.0.1:8000/petitions',data=json.dumps({'petition':'Synthetic load example: attendance is 72% due to illness. What rules apply?','synthetic':True}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        run = json.load(urllib.request.urlopen(request))
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            response = json.load(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000'+run['poll_url'],headers={'Authorization':'Bearer '+key})))
            if response['status'] in ('SUCCEEDED','FAILED'): break
            time.sleep(.2)
        else: raise RuntimeError('Warmup workflow deadline exceeded')
        if response['status']!='SUCCEEDED': raise RuntimeError('Warmup workflow failed')
        prefix=f'load_w{workers}_cache{cache}'
        load=command(['run','--rm','--no-deps','load','python','-m','locust','-f','load/locustfile.py','--host','http://api:8000','--headless','-u','10','-r','2','-t',f'{args.seconds}s','--stop-timeout','35','--csv',f'/app/evaluations/{prefix}'],env,check=False)
        command(['cp',f'api:/app/evaluations/{prefix}_stats.csv',str(ROOT/'evaluations'/f'{prefix}_stats.csv')],env)
        stats=list(csv.DictReader((ROOT/'evaluations'/f'{prefix}_stats.csv').open(encoding='utf-8')))
        completion=next(row for row in stats if row['Type']=='WORKFLOW')
        submit=next(row for row in stats if row['Name']=='/petitions')
        failure_ratio=float(completion['Failure Count'])/max(1,float(completion['Request Count']))
        row=dict(workers=workers,cache_ttl=cache,duration_seconds=args.seconds,concurrency=10,
                 workflow_rps=float(completion['Requests/s']),workflow_p50_ms=float(completion['50%']),
                 workflow_p95_ms=float(completion['95%']),submit_p95_ms=float(submit['95%']),failure_ratio=failure_ratio,
                 requests=int(completion['Request Count']))
        cache_rows=[item for item in stats if item['Type']=='CACHE']
        row['cache_hits']=sum(int(item['Request Count']) for item in cache_rows if item['Name']=='hit')
        row['cache_misses']=sum(int(item['Request Count']) for item in cache_rows if item['Name']=='miss')
        row['avoided_simulated_model_calls']=round(sum(float(item['Average Content Size'])*int(item['Request Count']) for item in cache_rows))
        row['estimated_billed_cost_usd']=0
        row['load_exit_code']=load.returncode
        row['slo_passed']=load.returncode==0 and row['workflow_p95_ms']<=slo['workflow_p95_ms'] and row['submit_p95_ms']<=slo['submission_p95_ms'] and failure_ratio<=slo['maximum_failure_ratio']
        rows.append(row)
        (ROOT/'evaluations/load_report.json').write_text(json.dumps(dict(deployment='Docker Compose',slo=slo,results=rows,hosted_requests=0),indent=2),encoding='utf-8')
    command(['up','-d','--no-deps','--scale','worker=3','--force-recreate','api','worker'])
    if not all(row['slo_passed'] for row in rows): raise SystemExit('One or more declared SLOs failed; inspect load_report.json before publication.')
    print('PASS: declared SLOs, one/three workers and cache comparison.')


if __name__=='__main__': main()
