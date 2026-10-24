"""Separate queue worker. Default mode uses a simulated model and local tools only."""
import argparse
import json
import signal
import threading
import time
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4
from assessment import PetitionRequest
from job_store import JobStore
from service_config import ServiceSettings
from operations import Operations
from telemetry import span

class Worker:
    def __init__(self, store, settings, runner=None):
        self.store, self.settings = store, settings
        self.worker_id = str(uuid4())
        self.runner = runner or self.execute
        self.operations = Operations(store)
        self.stub_client = None

    def execute(self, petition, mode):
        execution_started = time.monotonic()
        request = PetitionRequest(petition=petition)
        if mode not in ('stub','deterministic','hosted') or (mode=='hosted' and not self.settings.allow_hosted):
            raise ValueError('Execution mode is not enabled')
        failure = None
        if mode == 'stub' and os.getenv('STUB_SERVICE_URL'):
            from resilience import StubClient, ServiceUnavailable
            self.stub_client = self.stub_client or StubClient(os.environ['STUB_SERVICE_URL'], timeout=min(60,self.settings.job_timeout/3))
            try:
                return self.stub_client.run(request.petition)
            except ServiceUnavailable as exc:
                failure = str(exc)
                mode = 'deterministic'
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='job-',dir=self.store.path.parent) as directory:
            output = Path(directory)/'result.json'
            payload = dict(petition=request.petition,mode=mode,delay=self.settings.stub_delay_seconds,output=str(output))
            remaining = self.settings.job_timeout-(time.monotonic()-execution_started)
            if remaining<=0: raise subprocess.TimeoutExpired('job',self.settings.job_timeout)
            from telemetry import carrier
            payload['traceparent'] = carrier()
            subprocess.run([sys.executable,str(root/'src/run_job.py')],input=json.dumps(payload),text=True,encoding='utf-8',
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=remaining,
                           check=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            if output.stat().st_size>200000: raise ValueError('Output budget exceeded')
            result = json.loads(output.read_text(encoding='utf-8'))
            if failure: result['service_fallback'] = failure
            return result

    def run_once(self):
        self.store.touch_worker(self.worker_id)
        job = self.store.claim(self.worker_id, self.settings.lease_seconds)
        if job is None:
            return False
        stop = threading.Event()
        def heartbeat():
            while not stop.wait(min(5, self.settings.lease_seconds / 3)):
                self.store.touch_worker(self.worker_id)
                if not self.store.renew(job['run_id'], job['lease_token'], self.settings.lease_seconds):
                    break
        beat = threading.Thread(target=heartbeat, daemon=True)
        beat.start()
        started = time.monotonic()
        event = {'event': 'job_finished', 'run_id': job['run_id'], 'correlation_id': job['correlation_id'], 'mode': job['mode']}
        try:
            # Validate again at the worker boundary before calling even an injected runner.
            request = PetitionRequest(petition=job['petition'])
            from safety import check_input, guarded_result
            check_input(request.petition)
            with span('worker.job',parent=job.get('traceparent'),run_id=job['run_id'],correlation_id=job['correlation_id']) as current:
                cached = self.operations.cached(job.get('cache_key'))
                raw = cached if cached else self.runner(request.petition, job['mode'])
                result = guarded_result(raw, request.petition)
                result['trace_id'] = format(current.get_span_context().trace_id,'032x')
                result['cache'] = {'hit':bool(cached),'avoided_model_calls':sum(metric['model_calls'] for metric in raw.get('metrics',[])) if cached else 0}
                if cached:
                    result.update(metrics=[],usage=[],billable_model_requests=0,provider_response_used=False)
                result['reliability'] = {'fallback':raw.get('service_fallback') in ('CIRCUIT_OPEN','STUB_UNAVAILABLE'),
                                         'reason':raw.get('service_fallback') if raw.get('service_fallback') in ('CIRCUIT_OPEN','STUB_UNAVAILABLE') else None,
                                         'job_attempt':job['attempts']}
                if not cached: self.operations.cache(job.get('cache_key'),result,int(os.getenv('TRIAGE_CACHE_TTL','0')))
                from position import position
                from entities import extract_entities
                result['entities'] = extract_entities(request.petition)
                result['position'] = position(request.petition,json.loads(job['facts_json']) if job.get('facts_json') else None,result)
            accepted = self.store.finish(job['run_id'], job['lease_token'], result=result)
            event.update(status='SUCCEEDED' if accepted else 'LEASE_LOST')
        except Exception as exc:
            accepted = self.store.finish(job['run_id'], job['lease_token'], error={'code': 'WORKFLOW_TIMEOUT' if isinstance(exc,subprocess.TimeoutExpired) else 'WORKFLOW_FAILED', 'exception_type': type(exc).__name__})
            event.update(status='FAILED' if accepted else 'LEASE_LOST')
        finally:
            stop.set()
            beat.join(timeout=2)
        event['latency_seconds'] = round(time.monotonic() - started, 4)
        print(json.dumps(event), flush=True)
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-interval', type=float, default=.25)
    args = parser.parse_args()
    if args.poll_interval <= 0:
        parser.error('poll interval must be positive')
    settings = ServiceSettings.from_env()
    store = JobStore(settings.db_path)
    store.initialize()
    worker = Worker(store, settings)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    print(json.dumps({'event': 'worker_started', 'worker_id': worker.worker_id, 'mode': settings.mode}), flush=True)
    while not stop.is_set():
        processed = worker.run_once()
        if args.once:
            break
        if not processed:
            stop.wait(args.poll_interval)

if __name__ == '__main__':
    main()
