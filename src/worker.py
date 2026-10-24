"""Separate queue worker. Default mode uses a simulated model and local tools only."""
import argparse
import json
import signal
import threading
import time
from uuid import uuid4
from assessment import PetitionRequest
from job_store import JobStore
from service_config import ServiceSettings

class Worker:
    def __init__(self, store, settings, runner=None):
        self.store, self.settings = store, settings
        self.worker_id = str(uuid4())
        self.runner = runner or self.execute

    def execute(self, petition, mode):
        request = PetitionRequest(petition=petition)
        if mode == 'stub':
            from stub_model import run_stub
            return run_stub(request.petition, self.settings.stub_delay_seconds)
        if mode == 'deterministic':
            from workflow import run_petition
            result = run_petition(request.petition)
            result.pop('evidence', None)
            return result | {'mode': 'DETERMINISTIC', 'billable_model_requests': 0}
        raise ValueError('Hosted mode is not enabled in the service')

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
            result = guarded_result(self.runner(request.petition, job['mode']), request.petition)
            accepted = self.store.finish(job['run_id'], job['lease_token'], result=result)
            event.update(status='SUCCEEDED' if accepted else 'LEASE_LOST')
        except Exception as exc:
            accepted = self.store.finish(job['run_id'], job['lease_token'], error={'code': 'WORKFLOW_FAILED', 'exception_type': type(exc).__name__})
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
