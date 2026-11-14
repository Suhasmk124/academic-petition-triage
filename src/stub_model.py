"""A simulated model that exercises real tools and contracts, never a hosted API."""
import json
import time
from assessment import MISSING_EVIDENCE, PROVISIONS, classify

class StubChat:
    events = []
    def __init__(self, delay=.15, *, omit_first_pass=False):
        self.delay = delay
        self.events = []
        self.omit_first_pass = omit_first_pass

    def complete(self, role, messages, tools):
        self.events.append(dict(agent=role,input_tokens=(len(json.dumps(messages))+3)//4,output_tokens=0,
                                estimated=True,billed_cost_usd=0.0))
        result = self._complete(role,messages,tools)
        self.events[-1]['output_tokens'] = (len(json.dumps(result))+3)//4
        return result

    def _complete(self, role, messages, tools):
        time.sleep(self.delay)
        payload = json.loads(messages[1]['content'])
        outputs = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
        if role == 'investigator':
            expected = PROVISIONS[classify(payload['petition'])]
            citations = {c['clause_id']: c for result in outputs for c in result.get('citations', [])}
            if not outputs:
                return self.call('search_regulations', {'query': (payload.get('research_query') or payload['petition'])[:3000]}, len(messages))
            missing = [locator for locator in expected if locator not in citations]
            if missing:
                return self.call('fetch_exact_clause', {'clause_id': missing[0]}, len(messages))
            draft = {'claims': [{'claim_id': f'c{i}', 'statement': citations[locator]['exact_quote'],
                                 'evidence_id': citations[locator]['evidence_id']} for i, locator in enumerate(expected, 1)],
                     'missing_evidence': MISSING_EVIDENCE[classify(payload['petition'])],
                     'routing_recommendation': 'REFER_TO_COMMITTEE',
                     'reasons': ['Simulated extractive workflow; no real LLM semantic judgment.']}
            if any(schema['function']['parameters'].get('title')=='InvestigationSelection' for schema in tools):
                for claim in draft['claims']:claim.pop('statement',None)
            if self.omit_first_pass and not payload.get('research_query'):
                draft['claims'] = draft['claims'][:1]
            return {'role': 'assistant', 'content': json.dumps(draft)}
        if not outputs:
            return self.call('verify_claim_quotes', payload['quote_check_arguments'], len(messages))
        checked = {r['evidence_id']: r['quote_supported'] for output in outputs for r in output.get('results', [])}
        claims = payload['claims'] if 'claims' in payload else payload['draft']['claims']
        required = payload.get('required_provisions')
        clauses = [claim.get('clause_id') for claim in claims]
        verdicts = [{'claim_id': c['claim_id'], 'supported': bool(checked.get(c['evidence_id'])) and (
                     required is None or (c['clause_id'] in required and clauses.count(c['clause_id']) == 1)),
                     'reason': 'Simulated extractive quote check, not an LLM semantic judgment.'} for c in claims]
        missing = required is not None and not set(required).issubset(clauses)
        if any(schema.get('function',{}).get('parameters',{}).get('title')=='ReviewDecision' for schema in tools):
            for verdict in verdicts:verdict.pop('reason',None)
        return {'role': 'assistant', 'content': json.dumps({'verdicts': verdicts,
                'needs_research': missing or not all(v['supported'] for v in verdicts), 'research_query': ''})}

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


if __name__ == '__main__':
    from argparse import ArgumentParser
    from agent_workflow import run_agents
    from safety import guarded_result

    parser = ArgumentParser(description='Demonstrate the source auditor repairing a deliberately incomplete simulated handoff.')
    parser.add_argument('--demo-audit-retry', action='store_true', required=True)
    parser.parse_args()
    petition = 'My attendance is 72% due to illness. What are the medical condonation requirements?'
    raw = run_agents(petition, StubChat(0, omit_first_pass=True), variant='strict')
    result = guarded_result(raw, petition)
    history = result.get('agent_handoff', [])
    print(json.dumps({'simulation': True, 'status': result['status'], 'agent_handoff': history}, indent=2))
    if [step['outcome'] for step in history] != ['RETRY', 'REVIEW_REQUIRED']:
        raise SystemExit('The audit retry demonstration did not reach a verified brief.')
