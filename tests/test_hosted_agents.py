"""Simulated LLM and HTTP checks; never contacts a hosted provider."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from agent_workflow import EvidenceTools, SCHEMAS, Draft, critical_detail_errors, run_agents, run_hosted
from hosted_model import HostedChat, HostedSettings, ModelUnavailable

CITATION = {'evidence_id': 'fixture-attendance', 'exact_quote': 'Attendance must be at least 80%.',
            'citation_metadata_verified': True, 'section': '8.1', 'pdf_page': 37}
CLAIM = {'claim_id': 'c1', 'statement': 'The rule requires at least 80% attendance.',
         'evidence_id': CITATION['evidence_id'], 'supporting_quote': CITATION['exact_quote']}
DRAFT = {'claims': [CLAIM], 'missing_evidence': ['Official attendance record.'],
         'routing_recommendation': 'REFER_TO_COMMITTEE', 'reasons': ['Human review required.']}
REVIEW = {'verdicts': [{'claim_id': 'c1', 'supported': True, 'reason': 'Threshold matches the quote.'}],
          'needs_research': False, 'research_query': ''}

def final(content):
    if 'claims' in content:
        content = copy.deepcopy(content)
        for claim in content['claims']:
            claim.pop('supporting_quote', None)
    return {'role': 'assistant', 'content': json.dumps(content)}

def call(name, arguments):
    return {'role': 'assistant', 'content': None, 'tool_calls': [
        {'id': 'call-fixture', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}

def search_call():
    return call('search_regulations', {'query': 'attendance'})

def verify_call():
    return call('verify_claim_quotes', {'evidence_ids': [CLAIM['evidence_id']]})

class ScriptedModel:
    events = []
    def __init__(self, investigator=None, verifier=None):
        self.script = {'investigator': investigator or [search_call(), final(DRAFT)],
                       'verifier': verifier or [verify_call(), final(REVIEW)]}
        self.calls = []
    def complete(self, role, messages, tools):
        self.calls.append((role, copy.deepcopy(messages), tools))
        return self.script[role].pop(0)

def fixture_tools():
    return EvidenceTools(search=lambda args: json.dumps({'status': 'CANDIDATES_RETRIEVED', 'passages': [{'citations': [CITATION]}]}),
                         fetch=lambda args: json.dumps({'status': 'FOUND', 'citations': [CITATION]}),
                         quote_check=lambda args: json.dumps({'quote_supported': args['quote'] == CITATION['exact_quote']}))

class AgentTests(unittest.TestCase):
    def test_critical_portal_and_issuer_errors_are_rejected(self):
        draft = Draft.model_validate({'claims': [
            {'claim_id': 'portal', 'statement': 'Apply on the SAP portal within seven days.', 'evidence_id': 'portal', 'supporting_quote': 'SLCM application; SAP upload.'},
            {'claim_id': 'issuer', 'statement': 'Certificate issued by CMO, Health Centre or IISc.', 'evidence_id': 'issuer', 'supporting_quote': 'CMO, Health Centre, IISc.'}]})
        errors = critical_detail_errors(draft, {'portal': {'clause_id': '8.1(iii)'}, 'issuer': {'clause_id': '8.1(ii)'}})
        self.assertEqual(set(errors), {'portal', 'issuer'})

    def test_provider_schemas_inline_nested_argument_fields(self):
        schema = next(s for s in SCHEMAS if s['function']['name'] == 'verify_claim_quotes')
        parameters = schema['function']['parameters']
        self.assertNotIn('$ref', json.dumps(parameters))
        self.assertEqual(parameters['properties']['evidence_ids']['items']['type'], 'string')

    def run_model(self, model):
        with patch('workflow.run_petition', return_value={'status': 'ESCALATE', 'assessment': {'findings': []}}):
            return run_agents('My attendance is 72% due to illness.', model, fixture_tools(),variant='baseline')

    def test_two_roles_choose_tools_and_handoff(self):
        model = ScriptedModel()
        result = self.run_model(model)
        self.assertEqual(result['mode'], 'HOSTED_AGENTS')
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertEqual(result['draft']['claims'][0]['citation'], CITATION)
        self.assertEqual([m['tools_used'] for m in result['metrics']], [['search_regulations'], ['verify_claim_quotes']])
        self.assertEqual(len(SCHEMAS), 3)
        self.assertNotEqual(model.calls[0][1][0]['content'], model.calls[2][1][0]['content'])
        self.assertEqual([m['role'] for m in model.calls[2][1]], ['system', 'user'])
        self.assertFalse(result['provider_response_used'])
        self.assertFalse(result['final_decision_made'])

    def test_structured_json_submission_channel(self):
        draft=copy.deepcopy(DRAFT)
        for claim in draft['claims']:claim.pop('supporting_quote',None)
        model=ScriptedModel(investigator=[search_call(),call('JSON',draft)],verifier=[verify_call(),call('JSON',REVIEW)])
        result=self.run_model(model)
        self.assertEqual(result['mode'],'HOSTED_AGENTS')
        self.assertEqual(result['status'],'REVIEW_REQUIRED')
        self.assertEqual([metric['tools_used'] for metric in result['metrics']],[['search_regulations'],['verify_claim_quotes']])

    def test_json_submission_cannot_bypass_source_tools(self):
        draft=copy.deepcopy(DRAFT)
        for claim in draft['claims']:claim.pop('supporting_quote',None)
        result=self.run_model(ScriptedModel(investigator=[call('JSON',draft)]))
        self.assertEqual(result['mode'],'DETERMINISTIC_FALLBACK')

    def test_malformed_final_can_be_corrected_within_existing_budget(self):
        for malformed in (final({}),call('JSON',{})):
            model=ScriptedModel(investigator=[search_call(),malformed,final(DRAFT)])
            result=self.run_model(model)
            self.assertEqual(result['mode'],'HOSTED_AGENTS')
            self.assertEqual(result['metrics'][0]['model_calls'],3)
            self.assertIn('schema',json.dumps(model.calls[2][1]).lower())

    def test_malformed_final_cannot_expand_six_turn_limit(self):
        model=ScriptedModel(investigator=[search_call()]+[final({})]*8)
        result=self.run_model(model)
        self.assertEqual(result['mode'],'DETERMINISTIC_FALLBACK')
        self.assertEqual(result['metrics'][0]['model_calls'],6)

    def test_research_recovers_once(self):
        failed = copy.deepcopy(REVIEW)
        failed['verdicts'][0]['supported'] = False
        failed['needs_research'] = True
        failed['research_query'] = 'Find exact attendance threshold.'
        model = ScriptedModel(investigator=[search_call(), final(DRAFT)] * 2,
                              verifier=[verify_call(), final(failed), verify_call(), final(REVIEW)])
        result = self.run_model(model)
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertEqual(result['passes'], 2)

    def test_repeated_unsupported_claim_escalates_and_clears(self):
        failed = copy.deepcopy(REVIEW)
        failed['verdicts'][0]['supported'] = False
        model = ScriptedModel(investigator=[search_call(), final(DRAFT)] * 2,
                              verifier=[verify_call(), final(failed)] * 2)
        result = self.run_model(model)
        self.assertEqual(result['status'], 'ESCALATE')
        self.assertEqual(result['draft']['claims'], [])
        self.assertEqual(result['passes'], 2)

    def test_retrieval_must_be_model_selected(self):
        result = self.run_model(ScriptedModel(investigator=[final(DRAFT)]))
        self.assertEqual(result['mode'], 'DETERMINISTIC_FALLBACK')

    def test_unknown_tool_cannot_execute(self):
        result = self.run_model(ScriptedModel(investigator=[call('delete_file', {'path': 'data'})]))
        self.assertEqual(result['mode'], 'DETERMINISTIC_FALLBACK')

    def test_fabricated_evidence_falls_back(self):
        fake = copy.deepcopy(DRAFT)
        fake['claims'][0]['evidence_id'] = 'invented'
        result = self.run_model(ScriptedModel(investigator=[search_call(), final(fake)]))
        self.assertEqual(result['mode'], 'DETERMINISTIC_FALLBACK')

    def test_verifier_must_check_quotes_itself(self):
        result = self.run_model(ScriptedModel(verifier=[final(REVIEW)]))
        self.assertEqual(result['mode'], 'DETERMINISTIC_FALLBACK')

    def test_investigator_checks_do_not_count_for_verifier(self):
        model = ScriptedModel(investigator=[search_call(), verify_call(), final(DRAFT)], verifier=[final(REVIEW)])
        self.assertEqual(self.run_model(model)['mode'], 'DETERMINISTIC_FALLBACK')

    def test_missing_claim_verdict_falls_back(self):
        fake = copy.deepcopy(REVIEW)
        fake['verdicts'][0]['claim_id'] = 'different'
        self.assertEqual(self.run_model(ScriptedModel(verifier=[verify_call(), final(fake)]))['mode'], 'DETERMINISTIC_FALLBACK')

    def test_model_loop_is_bounded(self):
        model = ScriptedModel(investigator=[search_call()] * 8)
        result = self.run_model(model)
        self.assertEqual(result['mode'], 'DETERMINISTIC_FALLBACK')
        self.assertEqual(len(model.calls), 6)

    def test_bad_json_falls_back(self):
        model = ScriptedModel(investigator=[search_call(), {'role': 'assistant', 'content': 'not json'}])
        self.assertEqual(self.run_model(model)['mode'], 'DETERMINISTIC_FALLBACK')

    def test_no_config_means_no_network_model(self):
        with patch('agent_workflow.HostedSettings.from_env', side_effect=ModelUnavailable('missing')), patch('agent_workflow.HostedChat') as adapter, patch('workflow.run_petition', return_value={'status': 'REVIEW_REQUIRED'}):
            result = run_hosted('Attendance')
            adapter.assert_not_called()
            self.assertEqual(result['mode'], 'DETERMINISTIC_FALLBACK')

class AdapterTests(unittest.TestCase):
    def settings(self):
        return HostedSettings(base_url='https://provider.invalid/v1', model='fixture-model',
                              api_key='fixture-secret', free_plan_confirmed=True)

    def test_free_plan_confirmation_required(self):
        with self.assertRaises(ModelUnavailable):
            HostedSettings(base_url='https://provider.invalid/v1', model='fixture', api_key='fixture-secret')

    def test_secret_not_in_settings_repr(self):
        self.assertNotIn('fixture-secret', repr(self.settings()))

    def test_non_https_url_rejected(self):
        with self.assertRaises(ModelUnavailable):
            HostedSettings(base_url='http://provider.invalid', model='fixture', api_key='x', free_plan_confirmed=True)

    def test_quota_error_not_retried_or_routed_elsewhere(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(429, json={'error': 'quota'})
        client = httpx.Client(transport=httpx.MockTransport(respond))
        model = HostedChat(self.settings(), client=client)
        with self.assertRaises(ModelUnavailable):
            model.complete('investigator', [], [])
        self.assertEqual(len(requests), 1)
        self.assertNotIn('fixture-secret', json.dumps(model.events))

    def test_transient_retry_and_usage(self):
        count = []
        def respond(request):
            count.append(request)
            if len(count) == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
                                            'usage': {'prompt_tokens': 10, 'completion_tokens': 3}})
        model = HostedChat(self.settings(), client=httpx.Client(transport=httpx.MockTransport(respond)), sleep=lambda _: None)
        model.complete('verifier', [], [])
        self.assertEqual(len(count), 2)
        self.assertEqual(model.events[-1]['input_tokens'], 10)
        self.assertIsNone(model.events[-1]['billed_cost_usd'])

    def test_pacing_uses_provider_token_headers(self):
        sleeps = []
        def respond(request):
            return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}}]},
                headers={'x-ratelimit-remaining-tokens': '1', 'x-ratelimit-limit-tokens': '8000',
                         'x-ratelimit-reset-tokens': '2s'})
        model = HostedChat(self.settings(), client=httpx.Client(transport=httpx.MockTransport(respond)),
                           sleep=sleeps.append, clock=lambda: 1)
        model.complete('investigator', [], [])
        model.complete('verifier', [], [])
        self.assertEqual(sleeps, [3.0])
        self.assertEqual(model.events[-1]['pacing_seconds'], 3.0)

    def test_provider_error_diagnostic_redacts_key(self):
        def respond(request):
            return httpx.Response(400, json={'error': {'code': 'tool_use_failed', 'message': 'fixture-secret must not leak'}})
        model = HostedChat(self.settings(), client=httpx.Client(transport=httpx.MockTransport(respond)))
        with self.assertRaises(ModelUnavailable):
            model.complete('verifier', [], [])
        self.assertNotIn('fixture-secret', json.dumps(model.events))
        self.assertEqual(model.events[-1]['provider_error_code'], 'tool_use_failed')

    def test_circuit_opens_after_three_failed_calls(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(401)
        model = HostedChat(self.settings(), client=httpx.Client(transport=httpx.MockTransport(respond)), clock=lambda: 1)
        for _ in range(4):
            with self.assertRaises(ModelUnavailable):
                model.complete('verifier', [], [])
        self.assertEqual(len(requests), 3)

if __name__ == '__main__':
    unittest.main()
