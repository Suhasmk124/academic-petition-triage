"""Real local HTTP + separate worker smoke test. Hosted credentials are disabled in child processes."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from job_store import JobStore

ROOT = Path(__file__).resolve().parents[1]

def main():
    (ROOT / 'work').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='service-smoke-', dir=ROOT / 'work', ignore_cleanup_errors=True) as directory:
        folder = Path(directory)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = dict(os.environ, TRIAGE_DB_PATH=str(folder / 'service.sqlite3'), TRIAGE_MODE='stub',
                   TRIAGE_STUB_DELAY_SECONDS='0', LLM_API_KEY='', LLM_FREE_PLAN_CONFIRMED='false',
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', ANONYMIZED_TELEMETRY='False',
                   PYTHONIOENCODING='utf-8')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        handles, processes = [], []
        def start(command, name):
            output = (folder / f'{name}.log').open('w', encoding='utf-8')
            handles.append(output)
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output,
                                       stderr=subprocess.STDOUT, creationflags=flags)
            processes.append(process)
            return process
        api_command = [sys.executable, '-m', 'uvicorn', 'api:app', '--app-dir', 'src', '--host', '127.0.0.1', '--port', str(port)]
        base = f'http://127.0.0.1:{port}'
        def wait_http(path, deadline=30):
            until = time.monotonic() + deadline
            while time.monotonic() < until:
                try:
                    response = httpx.get(base + path, timeout=2)
                    if response.status_code == 200:
                        return response.json()
                except httpx.TransportError:
                    pass
                if any(p.poll() is not None for p in processes):
                    # Previously terminated API processes are expected after restart.
                    live = [p for p in processes if p.poll() is None]
                    if not live:
                        raise AssertionError('Service processes exited')
                time.sleep(.1)
            raise AssertionError(f'Timed out waiting for {path}')
        def poll(url):
            until = time.monotonic() + 150
            observed = {'QUEUED'}
            while time.monotonic() < until:
                response = httpx.get(base + url, timeout=3)
                response.raise_for_status()
                result = response.json()
                observed.add(result['status'])
                if result['status'] in ('SUCCEEDED', 'FAILED'):
                    return result, sorted(observed)
                time.sleep(.2)
            raise AssertionError('Timed out waiting for workflow completion')
        try:
            api = start(api_command, 'api')
            worker = start([sys.executable, 'src/worker.py'], 'worker')
            wait_http('/health')
            wait_http('/ready')
            invalid = httpx.post(base + '/petitions', json={'petition': ' ', 'synthetic': True}, timeout=3)
            assert invalid.status_code == 422 and invalid.json()['workflow_started'] is False
            store = JobStore(folder / 'service.sqlite3')
            with store.connection() as con:
                assert con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0
                assert con.execute('SELECT COUNT(*) FROM quarantine').fetchone()[0] == 1
            started = time.monotonic()
            accepted = httpx.post(base + '/petitions', json={'petition': 'Public-handbook synthetic demo: what are the attendance condonation requirements?', 'synthetic': True}, timeout=3)
            submit_seconds = time.monotonic() - started
            assert accepted.status_code == 202, accepted.text
            completed, observed = poll(accepted.json()['poll_url'])
            assert completed['status'] == 'SUCCEEDED', completed
            assert completed['triage_status'] == 'REVIEW_REQUIRED'
            assert completed['result']['mode'] == 'STUB'
            assert completed['result']['billable_model_requests'] == 0
            assert completed['result']['final_decision_made'] is False
            assert len(completed['result']['draft']['claims']) == 3
            other = httpx.post(base + '/petitions', json={'petition': 'Synthetic request to refund a parking ticket.', 'synthetic': True}, timeout=3)
            assert other.status_code == 202
            unsupported, _ = poll(other.json()['poll_url'])
            assert unsupported['status'] == 'SUCCEEDED' and unsupported['triage_status'] == 'ESCALATE'
            api.terminate()
            api.wait(timeout=10)
            api = start(api_command, 'api-restarted')
            wait_http('/health')
            persisted = httpx.get(base + accepted.json()['poll_url'], timeout=3).json()
            assert persisted['status'] == 'SUCCEEDED' and persisted['result'] == completed['result']
            report = dict(http_smoke_passed=True, default_mode='stub', hosted_credentials_disabled=True,
                          submit_status=202, observed_job_states=observed, submit_seconds=round(submit_seconds, 4),
                          cited_findings=3, invalid_status=422, invalid_request_started_workflow=False,
                          unsupported_triage='ESCALATE', result_survived_api_restart=True,
                          billable_model_requests=0,
                          scope='One local functional HTTP/worker smoke test, not a throughput benchmark or SLO measurement.')
            (ROOT / 'evaluations/service_smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('PASS: live local HTTP submission, polling, cited stub result, quarantine, unsupported escalation and API restart persistence.')
            return report
        except Exception:
            for output in handles:
                output.flush()
            for path in folder.glob('*.log'):
                lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
                print(path.name + ':\n' + '\n'.join(lines[-15:]))
            raise
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            for output in handles:
                output.close()

if __name__ == '__main__':
    main()
