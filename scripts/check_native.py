"""Pre-container verification of the real separate model service and three workers."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); return sock.getsockname()[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep-preview',action='store_true')
    args=parser.parse_args()
    api_port,stub_port=port(),port()
    (ROOT/'work').mkdir(exist_ok=True)
    processes=[]; handles=[]
    with tempfile.TemporaryDirectory(prefix='final-native-',dir=ROOT/'work',ignore_cleanup_errors=True) as directory:
        env=dict(os.environ,TRIAGE_MODE='stub',TRIAGE_DB_PATH=str(Path(directory)/'service.sqlite3'),
                 TRIAGE_API_KEY_FILE=str(ROOT/'.secrets/triage_key'),TRIAGE_CACHE_TTL='300',TRIAGE_RATE_LIMIT='0',
                 STUB_SERVICE_URL=f'http://127.0.0.1:{stub_port}',REDIS_URL='',OTEL_EXPORTER_OTLP_ENDPOINT='',
                 HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TRIAGE_PROMPT_VARIANT='strict',
                 LLM_API_KEY='',LLM_FREE_PLAN_CONFIRMED='false',PYTHONIOENCODING='utf-8')
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        def start(command,name):
            stream=(Path(directory)/(name+'.log')).open('w',encoding='utf-8'); handles.append(stream)
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=flags)
            processes.append(process); return process
        def wait(url,timeout=120):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                try:
                    if httpx.get(url,timeout=3).status_code==200:return
                except httpx.HTTPError:pass
                if any(process.poll() is not None for process in processes):raise RuntimeError('A service process exited')
                time.sleep(.5)
            raise TimeoutError(url)
        try:
            start([sys.executable,'-m','uvicorn','api:app','--app-dir','src','--host','127.0.0.1','--port',str(api_port)],'api')
            start([sys.executable,'-m','uvicorn','stub_service:app','--app-dir','src','--host','127.0.0.1','--port',str(stub_port)],'stub')
            wait(f'http://127.0.0.1:{api_port}/health'); wait(f'http://127.0.0.1:{stub_port}/health')
            for number in range(3):start([sys.executable,'src/worker.py'],f'worker-{number}')
            wait(f'http://127.0.0.1:{api_port}/ready')
            subprocess.run([sys.executable,'scripts/verify_stack.py','--url',f'http://127.0.0.1:{api_port}'],cwd=ROOT,env=env,check=True)
            key=(ROOT/'.secrets/triage_key').read_text().strip()
            with httpx.Client(base_url=f'http://127.0.0.1:{api_port}',headers={'Authorization':'Bearer '+key},timeout=5) as client:
                assert client.get('/health').json()['active_workers']==3
                report=json.loads((ROOT/'evaluations/deployed_stack.json').read_text())
                assert any(row['cache_hit'] for row in report['checks'])
                report.update(deployment='Native pre-container verification',separate_stub_service=True,workers=3,hosted_requests=0)
                (ROOT/'evaluations/native_stack.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print('PASS: real separate stub service, authenticated API, three workers, cache reuse and all conditional positions.')
            if args.keep_preview:
                print(f'PREVIEW http://127.0.0.1:{api_port}/',flush=True)
                while True:time.sleep(5)
        except Exception:
            for stream in handles:stream.flush()
            for log in Path(directory).glob('*.log'):
                print(log.name+':\n'+'\n'.join(log.read_text(encoding='utf-8',errors='replace').splitlines()[-12:]))
            raise
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
            for stream in handles:stream.close()


if __name__=='__main__':main()
