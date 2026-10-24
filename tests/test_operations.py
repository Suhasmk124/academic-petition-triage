import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from api import create_app
from job_store import JobStore
from service_config import ServiceSettings
from operations import Operations,cache_key
from resilience import StubClient,ServiceUnavailable
from position import position,PetitionFacts
from pydantic import ValidationError
from test_safety_feedback import good_result
from safety import guarded_result
from worker import Worker


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.now=1000
        self.store=JobStore(Path(self.directory.name)/'test.sqlite3',clock=lambda:self.now); self.store.initialize()
    def tearDown(self): self.directory.cleanup()
    def test_atomic_rate_limit_and_window_reset(self):
        operations=Operations(self.store)
        self.assertTrue(operations.allow('client',2)); self.assertTrue(operations.allow('client',2))
        self.assertFalse(operations.allow('client',2)); self.assertTrue(operations.allow('other',2))
        self.now+=120; self.assertTrue(operations.allow('client',2))
    def test_cache_ttl_and_invalid_output_not_cached(self):
        operations=Operations(self.store); good=guarded_result(good_result(),'attendance')
        operations.cache('key',good,10); self.assertEqual(operations.cached('key')['status'],'REVIEW_REQUIRED')
        self.now+=11; self.assertIsNone(operations.cached('key'))
        operations.cache('bad',{'status':'ESCALATE'},10); self.assertIsNone(operations.cached('bad'))
    def test_cache_key_changes_for_inputs_and_modes(self):
        self.assertNotEqual(cache_key('attendance','stub'),cache_key('attendance','hosted'))
        self.assertNotEqual(cache_key('attendance','stub'),cache_key('attendance medical','stub'))
    def test_worker_cache_avoids_second_runner_and_revalidates(self):
        calls=[]
        worker=Worker(self.store,ServiceSettings(db_path=self.store.path),runner=lambda *_:calls.append(1) or good_result())
        with patch.dict(os.environ,{'TRIAGE_CACHE_TTL':'60'}):
            first=self.store.submit('attendance','stub',str(uuid4()),cache_key='same'); worker.run_once()
            second=self.store.submit('attendance','stub',str(uuid4()),cache_key='same'); worker.run_once()
        self.assertEqual(len(calls),1); self.assertTrue(self.store.get(second)['result']['cache']['hit'])
        self.assertFalse(self.store.get(first)['result']['cache']['hit'])
    def test_migration_preserves_existing_jobs(self):
        identifier=self.store.submit('attendance','stub',str(uuid4()),traceparent='fixture-parent',facts={'attendance_percent':85})
        self.store.initialize(); self.assertEqual(self.store.get(identifier)['status'],'QUEUED')
        self.assertNotIn('facts_json',self.store.get(identifier))


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(); self.store=JobStore(Path(self.directory.name)/'test.sqlite3')
        self.env=patch.dict(os.environ,{'TRIAGE_API_KEY':'local-fixture-key-for-tests','TRIAGE_API_KEY_FILE':'','TRIAGE_RATE_LIMIT':'2','REDIS_URL':''}); self.env.start()
        self.context=TestClient(create_app(ServiceSettings(db_path=self.store.path),self.store)); self.client=self.context.__enter__()
    def tearDown(self): self.context.__exit__(None,None,None); self.env.stop(); self.directory.cleanup()
    def test_key_and_browser_cookie(self):
        self.assertEqual(self.client.get('/quality-samples').status_code,401)
        self.assertEqual(self.client.post('/auth/session',json={'api_key':'wrong'}).status_code,401)
        response=self.client.post('/auth/session',json={'api_key':'local-fixture-key-for-tests'})
        self.assertEqual(response.status_code,200); self.assertIn('HttpOnly',response.headers['set-cookie'])
        self.assertEqual(self.client.get('/quality-samples').status_code,200)
    def test_bearer_rate_limit_and_metrics(self):
        self.client.headers['Authorization']='Bearer local-fixture-key-for-tests'
        for _ in range(2): self.assertEqual(self.client.post('/petitions',json={'petition':'attendance','synthetic':True}).status_code,202)
        limited=self.client.post('/petitions',json={'petition':'attendance','synthetic':True})
        self.assertEqual(limited.status_code,429)
        text=self.client.get('/metrics').text
        self.assertIn('triage_http_duration_seconds_bucket',text); self.assertIn('triage_jobs',text)
        self.assertNotIn('local-fixture-key',text)
    def test_cross_origin_state_change_rejected(self):
        self.client.headers['Authorization']='Bearer local-fixture-key-for-tests'
        response=self.client.post('/petitions',json={'petition':'attendance','synthetic':True},headers={'Origin':'https://outside.invalid'})
        self.assertEqual(response.status_code,403)
    def test_facts_contract(self):
        self.client.headers['Authorization']='Bearer local-fixture-key-for-tests'
        self.assertEqual(self.client.post('/petitions',json={'petition':'attendance','synthetic':True,'facts':{'attendance_percent':101}}).status_code,422)


class ResilienceTests(unittest.TestCase):
    def test_retry_backoff_then_success(self):
        calls=[]; sleeps=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(503 if len(calls)==1 else 200,json={'status':'REVIEW_REQUIRED'})
        client=StubClient('http://stub.invalid',transport=httpx.MockTransport(respond),sleep=sleeps.append)
        self.assertEqual(client.run('attendance')['status'],'REVIEW_REQUIRED'); self.assertEqual(sleeps,[.25])
    def test_circuit_opens_and_recovers(self):
        now=[0]; calls=[]
        def respond(request): calls.append(1); return httpx.Response(503)
        client=StubClient('http://stub.invalid',transport=httpx.MockTransport(respond),clock=lambda:now[0],sleep=lambda _:None)
        for _ in range(3):
            with self.assertRaises(ServiceUnavailable): client.run('attendance')
        with self.assertRaises(ServiceUnavailable): client.run('attendance')
        self.assertEqual(len(calls),6); now[0]=31
        with self.assertRaises(ServiceUnavailable): client.run('attendance')
        self.assertEqual(len(calls),8)


class PositionTests(unittest.TestCase):
    def test_entities_are_labeled_unverified(self):
        from entities import extract_entities
        result=extract_entities('My attendance is 72% in CS101. I applied on SLCM after illness on 2026-10-20.')
        self.assertEqual(result['stated_attendance_percent'],72)
        self.assertEqual(result['course_codes'],['CS101'])
        self.assertEqual(result['dates'],['2026-10-20']); self.assertFalse(result['facts_verified'])
    def test_conditional_grant_and_restriction(self):
        result=guarded_result(good_result(),'attendance')
        grant=position('attendance',{'attendance_percent':85},result)
        self.assertEqual(grant['recommendation'],'GRANT_UNDER_PROVISION'); self.assertFalse(grant['facts_verified'])
        restriction=position('attendance',{'attendance_percent':70,'medical_absence':False,'exception_requested':False},result)
        self.assertEqual(restriction['recommendation'],'REJECT_UNDER_PROVISION'); self.assertFalse(restriction['final_decision_made'])
    def test_medical_exception_and_missing_source_refer(self):
        result=guarded_result(good_result(),'attendance')
        self.assertEqual(position('attendance',{'attendance_percent':70,'medical_absence':True},result)['recommendation'],'REFER_TO_COMMITTEE')
        self.assertEqual(position('attendance',{'attendance_percent':90},{'status':'ESCALATE'})['recommendation'],'REFER_TO_COMMITTEE')
        self.assertEqual(position('My employee attendance is low',{'attendance_percent':90},result)['recommendation'],'REFER_TO_COMMITTEE')
    def test_invalid_boolean_rejected(self):
        with self.assertRaises(ValidationError): PetitionFacts(medical_absence=1)

    def test_conflicting_figures_do_not_produce_conditional_grant(self):
        result=guarded_result(good_result(),'attendance')
        self.assertEqual(position('My attendance is 70%',{'attendance_percent':90},result)['recommendation'],'REFER_TO_COMMITTEE')
