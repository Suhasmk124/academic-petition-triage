import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from api import create_app
from job_store import JobStore
from service_config import ServiceSettings
from review_export import review_packet,review_html
from position import position
from safety import guarded_result
from test_safety_feedback import good_result

class ExportTests(unittest.TestCase):
    def test_snapshot_omits_private_job_fields_and_escapes_html(self):
        packet=review_packet({'run_id':'fixture','status':'SUCCEEDED','petition':'PRIVATE','lease_token':'SECRET',
            'result':{'assessment':{'findings':[{'citation':{'clause_id':'<script>','pdf_page':37},'supporting_quote':'<img src=x onerror=alert(1)>'}]}}})
        output=review_html(packet)
        self.assertNotIn('PRIVATE',json.dumps(packet));self.assertNotIn('SECRET',json.dumps(packet))
        self.assertNotIn('<script>',output);self.assertNotIn('<img',output)
        self.assertIn('&lt;img',output);self.assertIn('an academic officer must decide',output)

    def test_authenticated_completed_export_and_invalid_states(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'TRIAGE_API_KEY':'export-test-key','TRIAGE_API_KEY_FILE':'','REDIS_URL':'','TRIAGE_RATE_LIMIT':'0'}):
            store=JobStore(Path(folder)/'jobs.sqlite3');store.initialize()
            run=store.submit('attendance','stub',str(uuid4()))
            with TestClient(create_app(ServiceSettings(db_path=store.path),store)) as client:
                path=f'/runs/{run}/export'
                self.assertEqual(client.get(path).status_code,401)
                client.headers['Authorization']='Bearer export-test-key'
                self.assertEqual(client.get(path).status_code,409)
                job=store.claim('fixture',120)
                store.finish(run,job['lease_token'],result=guarded_result(good_result(),'attendance'))
                response=client.get(path)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['schema_version'],'review-packet-v1')
                self.assertFalse(response.json()['final_decision_made'])
                self.assertEqual(response.headers['cache-control'],'no-store')
                html=client.get(path+'?format=html')
                self.assertIn('attachment;',html.headers['content-disposition'])
                self.assertIn("default-src 'none'",html.headers['content-security-policy'])
                self.assertIn('8.1(i)',html.text)
                self.assertEqual(client.get(path+'?format=exe').status_code,422)
                self.assertEqual(client.get(f'/runs/{uuid4()}/export').status_code,404)

class ConflictTests(unittest.TestCase):
    def test_ambiguous_and_invalid_percentages_cannot_produce_grant(self):
        result=guarded_result(good_result(),'attendance')
        for petition in ('My attendance was 60% then 90%.','My attendance is -10%.','My attendance is 1000%.'):
            with self.subTest(petition=petition):
                self.assertEqual(position(petition,{'attendance_percent':90},result)['recommendation'],'REFER_TO_COMMITTEE')
    def test_medical_text_cannot_be_overridden_by_structured_no(self):
        result=guarded_result(good_result(),'attendance')
        route=position('My attendance is 70% because of illness.',{'attendance_percent':70,'medical_absence':False,'exception_requested':False},result)
        self.assertEqual(route['recommendation'],'REFER_TO_COMMITTEE')

    def test_oversized_percentage_is_json_safe_and_refers(self):
        from entities import extract_entities
        petition='My attendance is '+('9'*400)+'%.'
        json.dumps(extract_entities(petition),allow_nan=False)
        result=guarded_result(good_result(),'attendance')
        self.assertEqual(position(petition,{'attendance_percent':90},result)['recommendation'],'REFER_TO_COMMITTEE')
