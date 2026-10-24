import json
import sys
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import subprocess
import tempfile
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from telemetry import span,carrier
from agent_workflow import run_agents,EvidenceTools
from stub_model import StubChat
from index_corpus import reviewed
from retrieval import citation,source_pages
from job_store import JobStore
from service_config import ServiceSettings
from worker import Worker
from test_safety_feedback import good_result


class TracePromptTests(unittest.TestCase):
    def test_trace_carrier_links_worker_and_agent(self):
        with span('http') as parent:
            token=carrier()
            with span('worker',parent=token) as child:
                self.assertEqual(parent.get_span_context().trace_id,child.get_span_context().trace_id)
                self.assertEqual(child.parent.span_id,parent.get_span_context().span_id)

    def run_variant(self,variant):
        rows=[citation(record) for record in reviewed(source_pages()) if record['metadata']['section']=='8.1']
        tools=EvidenceTools(search=lambda _:json.dumps({'citations':rows}),fetch=lambda _:json.dumps({'citations':rows}),quote_check=lambda _:json.dumps({'quote_supported':True}))
        return run_agents('attendance',StubChat(0),tools=tools,variant=variant)

    def test_strict_variant_and_token_attribution(self):
        result=self.run_variant('strict')
        self.assertEqual(result['status'],'REVIEW_REQUIRED')
        self.assertEqual([metric['prompt_version'] for metric in result['metrics']],['investigator_v4','verifier_v5'])
        self.assertTrue(result['model_usage'])
        self.assertTrue(all(event['estimated'] and event['billed_cost_usd']==0 for event in result['model_usage']))
        self.assertTrue(all(claim['statement']==claim['citation']['exact_quote'] for claim in result['draft']['claims']))
        self.assertTrue(all(metric['retries']==0 for metric in result['metrics']))

    def test_concurrent_prompt_selection_is_isolated(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            baseline,strict=list(pool.map(self.run_variant,['baseline','strict']))
        self.assertEqual(baseline['metrics'][0]['prompt_version'],'investigator_v2')
        self.assertEqual(strict['metrics'][0]['prompt_version'],'investigator_v4')

    def test_timeout_visible_without_exception_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            store=JobStore(Path(folder)/'service.sqlite3'); store.initialize()
            run_id=store.submit('attendance','stub',str(uuid4()))
            def timeout(*_): raise subprocess.TimeoutExpired('private fixture command',1)
            Worker(store,ServiceSettings(db_path=store.path),runner=timeout).run_once()
            result=store.get(run_id)
            self.assertEqual(result['error']['code'],'WORKFLOW_TIMEOUT')
            self.assertNotIn('private fixture',json.dumps(result))
