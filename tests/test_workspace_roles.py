import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from api import create_app
from fastapi.testclient import TestClient
from job_store import JobStore
from service_config import ServiceSettings


class WorkspaceRoleTests(unittest.TestCase):
    def test_showcase_password_roles_and_synthetic_guard(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{
            'TRIAGE_API_KEY':'independent-signing-key','TRIAGE_API_KEY_FILE':'','REDIS_URL':'','TRIAGE_RATE_LIMIT':'0'
        }):
            for showcase in (False, True):
                settings = ServiceSettings(db_path=Path(tmp)/f'roles-{showcase}.sqlite',
                                           private_records=True,role_accounts=True,role_demo=showcase)
                with TestClient(create_app(settings)) as client:
                    for role in ('admin','reviewer','student'):
                        response = client.post('/auth/session',json={'username':role,'api_key':'pass@1234'})
                        self.assertEqual(response.status_code,200 if showcase else 401)
                        if showcase:
                            self.assertEqual(client.get('/workspace/me').json(),{'username':role,'role':role})
                    if showcase:
                        payload = {'petition':'What are the attendance provisions?'}
                        self.assertEqual(client.post('/petitions/private',json=payload).status_code,422)
                        self.assertEqual(client.post('/petitions/private',json={**payload,'synthetic':True}).status_code,202)
                        self.assertEqual(client.post('/petitions',json={**payload,'synthetic':True}).status_code,403)
                        store = client.app.state.store
                        job = store.claim('showcase-test')
                        store.finish(job['run_id'],job['lease_token'],result={'status':'REVIEW_REQUIRED'})
                    client.cookies.clear()
                    self.assertEqual(client.get('/workspace/me',headers={'Authorization':'Bearer pass@1234'}).status_code,401)
                    metrics = client.get('/metrics',headers={'Authorization':'Bearer independent-signing-key'})
                    self.assertEqual(metrics.status_code,200)
                    count = '1.0' if showcase else '0.0'
                    self.assertIn(f'triage_workflow_duration_seconds_count{{status="SUCCEEDED"}} {count}',metrics.text)

    def test_student_isolation_staff_review_and_admin_provisioning(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{
            'TRIAGE_API_KEY':'admin-fixture-key','TRIAGE_API_KEY_FILE':'','REDIS_URL':'','TRIAGE_RATE_LIMIT':'0'
        }):
            store=JobStore(Path(tmp)/'roles.sqlite')
            settings=ServiceSettings(db_path=store.path,private_records=True,role_accounts=True)
            with TestClient(create_app(settings,store)) as client:
                admin={'Authorization':'Bearer admin-fixture-key'}
                password='fixture-only-password'
                for username,role in [('alice','student'),('bob','student'),('officer','reviewer')]:
                    response=client.post('/workspace/accounts',headers=admin,json={
                        'username':username,'role':role,'password':password})
                    self.assertEqual(response.status_code,201,response.text)
                    self.assertNotIn(password,store.account(username)['password_hash'])
                def login(username):
                    client.cookies.clear()
                    r=client.post('/auth/session',json={'username':username,'api_key':password})
                    self.assertEqual(r.status_code,200,r.text)
                login('alice')
                self.assertEqual(client.get('/workspace/me').json()['role'],'student')
                accepted=client.post('/petitions/private',json={'petition':'Attendance provisions','facts':{'attendance_percent':74}})
                self.assertEqual(accepted.status_code,202,accepted.text)
                path=accepted.json()['poll_url']
                self.assertEqual(client.get(path).json()['attendance_percent'],74)
                self.assertEqual(client.post('/workspace/accounts',json={}).status_code,403)
                self.assertEqual(client.put(path+'/officer-review',json={}).status_code,403)
                job=store.claim('fixture')
                store.finish(job['run_id'],job['lease_token'],result={'status':'REVIEW_REQUIRED'})
                login('bob')
                for suffix in ('','/export','/attachment','/feedback'):
                    self.assertEqual(client.get(path+suffix).status_code,404)
                self.assertEqual(client.delete(path+'/attachment').status_code,404)
                self.assertEqual(client.get('/workspace/cases').json(),[])
                login('officer')
                self.assertEqual(client.post('/petitions/private',json={'petition':'Attendance'}).status_code,403)
                self.assertEqual(len(client.get('/workspace/cases').json()),1)
                self.assertEqual(client.delete(path+'/attachment').status_code,403)
                review=client.put(path+'/officer-review',json={'outcome':'needs_information','note':'Please supply the attendance record.'})
                self.assertEqual(review.status_code,200,review.text)
                self.assertEqual(review.json()['reviewer'],'officer')
                login('alice')
                self.assertEqual(client.get(path).json()['officer_review']['outcome'],'needs_information')
                self.assertEqual(client.post('/auth/logout').status_code,204)
                self.assertEqual(client.get(path).status_code,401)
