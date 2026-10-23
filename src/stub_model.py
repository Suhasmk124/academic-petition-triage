"""A simulated model that exercises real tools and contracts, never a hosted API."""
import json
import time
from assessment import MISSING_EVIDENCE, PROVISIONS, classify

class StubChat:
    events = []
    def __init__(self, delay=.15):
        self.delay = delay

    def complete(self, role, messages, tools):
        time.sleep(self.delay)
        payload = json.loads(messages[1]['content'])
        outputs = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
        if role == 'investigator':
            expected = PROVISIONS[classify(payload['petition'])]
            citations = {c['clause_id']: c for result in outputs for c in result.get('citations', [])}
            if not outputs:
                return self.call('search_regulations', {'query': payload.get('research_query') or payload['petition']}, len(messages))
            missing = [locator for locator in expected if locator not in citations]
            if missing:
                return self.call('fetch_exact_clause', {'clause_id': missing[0]}, len(messages))
            draft = {'claims': [{'claim_id': f'c{i}', 'statement': citations[locator]['exact_quote'],
                                 'evidence_id': citations[locator]['evidence_id']} for i, locator in enumerate(expected, 1)],
                     'missing_evidence': MISSING_EVIDENCE[classify(payload['petition'])],
                     'routing_recommendation': 'REFER_TO_COMMITTEE',
                     'reasons': ['Simulated extractive workflow; no real LLM semantic judgment.']}
            return {'role': 'assistant', 'content': json.dumps(draft)}
        if not outputs:
            return self.call('verify_claim_quotes', payload['quote_check_arguments'], len(messages))
        checked = {r['evidence_id']: r['quote_supported'] for output in outputs for r in output.get('results', [])}
        verdicts = [{'claim_id': c['claim_id'], 'supported': checked.get(c['evidence_id'], False),
                     'reason': 'Simulated extractive quote check, not an LLM semantic judgment.'} for c in payload['draft']['claims']]
        return {'role': 'assistant', 'content': json.dumps({'verdicts': verdicts,
                'needs_research': not all(v['supported'] for v in verdicts), 'research_query': ''})}

    @staticmethod
    def call(name, args, sequence):
        return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'stub-{sequence}', 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(args)}}]}


def run_stub(petition, delay=.15):
    from agent_workflow import run_agents
    from workflow import run_petition
    if classify(petition) == 'UNSUPPORTED':
        result = run_petition(petition)
    else:
        result = run_agents(petition, StubChat(delay))
    path = 'TWO_ROLE_SIMULATED' if result.get('mode') == 'HOSTED_AGENTS' else 'DETERMINISTIC_FALLBACK'
    result.update(mode='STUB', stub_workflow_path=path, simulated=True, billable_model_requests=0,
                  semantic_review='SIMULATED_EXTRACTIVE_CHECK_NOT_LLM', provider_response_used=False)
    # Do not expose the internal raw retrieval candidates through the service result.
    result.pop('evidence', None)
    return result
