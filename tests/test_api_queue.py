"""API/queue regressions; runners are injected and hosted calls are forbidden."""
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fastapi.testclient import TestClient
from api import create_app
from job_store import JobStore, QueueFull
from service_config import ServiceSettings
from worker import Worker

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.store = JobStore(Path(self.directory.name) / 'service.sqlite3', clock=lambda: self.now)
        self.store.initialize()
    def tearDown(self):
        self.directory.cleanup()
    def submit(self):
        return self.store.submit('Synthetic attendance policy question.', 'stub', str(uuid4()))

    def test_job_survives_new_store_instance(self):
        run_id = self.submit()
        restored = JobStore(self.store.path)
        self.assertEqual(restored.get(run_id)['status'], 'QUEUED')
        self.assertNotIn('petition', restored.get(run_id))

    def test_atomic_claim_has_one_winner(self):
        self.submit()
        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(lambda i: self.store.claim(str(i)), range(8)))
        self.assertEqual(sum(job is not None for job in claimed), 1)

    def test_expired_lease_recovers_and_fences_old_worker(self):
        run_id = self.submit()
        first = self.store.claim('first', lease_seconds=10)
        self.now += 11
        second = self.store.claim('second', lease_seconds=10)
        self.assertEqual(second['run_id'], run_id)
        self.assertEqual(second['attempts'], 2)
        self.assertFalse(self.store.finish(run_id, first['lease_token'], result={'status': 'WRONG'}))
        self.assertTrue(self.store.finish(run_id, second['lease_token'], result={'status': 'REVIEW_REQUIRED'}))
        self.assertEqual(self.store.get(run_id)['status'], 'SUCCEEDED')

    def test_repeated_abandoned_lease_fails(self):
        run_id = self.submit()
        self.store.claim('first', lease_seconds=1)
        self.now += 2
        self.store.claim('second', lease_seconds=1)
        self.now += 2
        self.assertIsNone(self.store.claim('third'))
        self.assertEqual(self.store.get(run_id)['error']['code'], 'WORKER_LEASE_EXHAUSTED')

    def test_renew_prevents_reclaim(self):
        run_id = self.submit()
        job = self.store.claim('first', lease_seconds=10)
        self.now += 9
        self.assertTrue(self.store.renew(run_id, job['lease_token'], 10))
        self.now += 2
        self.assertIsNone(self.store.claim('second'))

    def test_capacity_checked_atomically(self):
        self.store.submit('One.', 'stub', str(uuid4()), capacity=1)
        with self.assertRaises(QueueFull):
            self.store.submit('Two.', 'stub', str(uuid4()), capacity=1)

class APITests(unittest.TestCase):
    def test_portal_and_assets_are_served_with_existing_api(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Petition desk', page.text)
        self.assertIn('no-cache', page.headers['cache-control'])
        self.assertEqual(self.client.get('/assets/app.js').status_code, 200)
        self.assertEqual(self.client.get('/assets/style.css').status_code, 200)
        self.assertEqual(self.client.get('/docs').status_code, 200)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = ServiceSettings(db_path=Path(self.directory.name) / 'service.sqlite3', stub_delay_seconds=0)
        self.store = JobStore(self.settings.db_path)
        self.client_context = TestClient(create_app(self.settings, self.store))
        self.client = self.client_context.__enter__()
        self.calls = []
        self.worker = Worker(self.store, self.settings, runner=self.fake_run)
    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.directory.cleanup()
    def fake_run(self, petition, mode):
        self.calls.append((petition, mode))
        return {'status': 'REVIEW_REQUIRED', 'mode': 'STUB', 'assessment': {'routing_recommendation': 'REFER_TO_COMMITTEE', 'final_decision_made': False}}
    def counts(self):
        with self.store.connection() as con:
            return (con.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],
                    con.execute('SELECT COUNT(*) FROM quarantine').fetchone()[0])
    def submit(self):
        return self.client.post('/petitions', json={'petition': 'Synthetic attendance policy question.', 'synthetic': True})

    def test_submit_returns_before_worker_then_poll_completes(self):
        response = self.submit()
        self.assertEqual(response.status_code, 202)
        accepted = response.json()
        self.assertEqual(accepted['mode'], 'stub')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.client.get(accepted['poll_url']).json()['status'], 'QUEUED')
        self.assertTrue(self.worker.run_once())
        finished = self.client.get(accepted['poll_url']).json()
        self.assertEqual(finished['status'], 'SUCCEEDED')
        self.assertEqual(finished['triage_status'], 'REVIEW_REQUIRED')
        self.assertEqual(finished['attempts'], 1)
        self.assertEqual(finished['correlation_id'], accepted['correlation_id'])
        self.assertNotIn('petition', finished)

    def test_invalid_inputs_quarantined_no_run_or_runner(self):
        payloads = [{}, {'petition': ' ', 'synthetic': True}, {'petition': 'x' * 4001, 'synthetic': True},
                    {'petition': 'Synthetic', 'synthetic': False}, {'petition': 'Synthetic', 'synthetic': 1},
                    {'petition': 123, 'synthetic': True}, {'petition': 'Synthetic', 'synthetic': True, 'mode': 'hosted'}]
        for payload in payloads:
            response = self.client.post('/petitions', json=payload)
            self.assertEqual(response.status_code, 422)
            self.assertFalse(response.json()['workflow_started'])
            self.assertNotIn('run_id', response.json())
        self.assertEqual(self.counts(), (0, len(payloads)))
        self.assertFalse(self.worker.run_once())
        self.assertEqual(self.calls, [])

    def test_malformed_json_quarantined(self):
        response = self.client.post('/petitions', content='{broken', headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.counts(), (0, 1))

    def test_body_limit_quarantines_bounded_prefix(self):
        response = self.client.post('/petitions', content='x' * 20000, headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 413)
        with self.store.connection() as con:
            row = con.execute('SELECT length(body),truncated FROM quarantine').fetchone()
        self.assertEqual(tuple(row), (16384, 1))
        self.assertEqual(self.counts(), (0, 1))

    def test_wrong_content_type_is_quarantined(self):
        self.assertEqual(self.client.post('/petitions', content='synthetic', headers={'Content-Type': 'text/plain'}).status_code, 415)
        self.assertEqual(self.counts(), (0, 1))

    def test_queue_full_returns_503_without_new_job(self):
        settings = ServiceSettings(db_path=self.settings.db_path, queue_capacity=1)
        with TestClient(create_app(settings, self.store)) as client:
            self.assertEqual(client.post('/petitions', json={'petition': 'Synthetic one', 'synthetic': True}).status_code, 202)
            response = client.post('/petitions', json={'petition': 'Synthetic two', 'synthetic': True})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['Retry-After'], '1')
        self.assertEqual(self.counts(), (1, 0))

    def test_unknown_and_malformed_run_ids(self):
        self.assertEqual(self.client.get('/runs/' + str(uuid4())).status_code, 404)
        self.assertEqual(self.client.get('/runs/not-a-uuid').status_code, 422)
        self.assertEqual(self.counts(), (0, 0))

    def test_readiness_tracks_worker_heartbeat(self):
        self.assertEqual(self.client.get('/ready').status_code, 503)
        self.assertFalse(self.worker.run_once())
        self.assertEqual(self.client.get('/ready').status_code, 200)
        self.assertEqual(self.client.get('/health').json()['mode'], 'stub')

    def test_worker_failure_visible_without_exception_payload(self):
        response = self.submit()
        def fail(*_):
            raise RuntimeError('sensitive fixture text must not be exposed')
        worker = Worker(self.store, self.settings, runner=fail)
        worker.run_once()
        finished = self.client.get(response.json()['poll_url']).json()
        self.assertEqual(finished['status'], 'FAILED')
        self.assertEqual(finished['error']['exception_type'], 'RuntimeError')
        self.assertNotIn('sensitive fixture text', json.dumps(finished))

    def test_service_rejects_hosted_configuration(self):
        with self.assertRaises(ValueError):
            ServiceSettings(mode='hosted')

    def test_worker_revalidates_before_runner(self):
        run_id = self.store.submit(' ', 'stub', str(uuid4()))
        self.worker.run_once()
        self.assertEqual(self.store.get(run_id)['status'], 'FAILED')
        self.assertEqual(self.calls, [])

    def test_submission_correlation_header_is_server_generated(self):
        response = self.client.post('/petitions', json={'petition': 'Synthetic policy question.', 'synthetic': True}, headers={'X-Correlation-ID': 'untrusted'})
        self.assertEqual(response.headers['X-Correlation-ID'], response.json()['correlation_id'])
        self.assertNotEqual(response.headers['X-Correlation-ID'], 'untrusted')

if __name__ == '__main__':
    unittest.main()
