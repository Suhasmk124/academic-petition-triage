"""Measure both HTTP endpoints and business completion latency, not only enqueue time."""
import os
import time
from pathlib import Path
from locust import HttpUser, task, between


class PetitionUser(HttpUser):
    wait_time = between(.05,.2)

    def on_start(self):
        key_file = os.getenv('TRIAGE_API_KEY_FILE')
        key = Path(key_file).read_text(encoding='utf-8').strip() if key_file else os.getenv('TRIAGE_API_KEY','')
        if key: self.client.headers.update({'Authorization':'Bearer '+key})

    @task
    def petition(self):
        started = time.monotonic()
        failure = None
        cache = None
        try:
            with self.client.post('/petitions',json={'petition':'Synthetic load example: attendance is 72% due to illness. What rules apply?','synthetic':True},catch_response=True,name='/petitions') as response:
                if response.status_code!=202:
                    response.failure('Submission did not return 202')
                    raise RuntimeError('Submission rejected')
                url = response.json()['poll_url']
            deadline = started+30
            while time.monotonic()<deadline:
                response = self.client.get(url,name='/runs/{id}')
                response.raise_for_status()
                run = response.json()
                if run['status']=='FAILED': raise RuntimeError('Worker failed')
                if run['status']=='SUCCEEDED':
                    result = run['result']
                    if result['status']!='REVIEW_REQUIRED' or result['safety']['output']!='passed' or result['final_decision_made']:
                        raise RuntimeError('Invalid cited workflow outcome')
                    cache = result.get('cache',{})
                    break
                time.sleep(.1)
            else: raise TimeoutError('Workflow deadline exceeded')
        except Exception as exc:
            failure = exc
        self.environment.events.request.fire(request_type='WORKFLOW',name='petition_to_completion',
            response_time=(time.monotonic()-started)*1000,response_length=0,exception=failure,context={})
        if cache is not None:
            self.environment.events.request.fire(request_type='CACHE',name='hit' if cache.get('hit') else 'miss',
                response_time=0,response_length=cache.get('avoided_model_calls',0),exception=None,context={})
