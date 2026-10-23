"""Two separately prompted LLM roles in LangGraph, with bounded model/tool calls."""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Literal, TypedDict
from pydantic import Field
from langgraph.graph import StateGraph, START, END
from assessment import Contract, PetitionRequest
from hosted_model import HostedChat, HostedSettings, ModelUnavailable

ROOT = Path(__file__).resolve().parents[1]
MAX_TURNS = 6
MAX_TOOLS = 6
MAX_PASSES = 2

class AgentFailure(RuntimeError):
    pass

class Claim(Contract):
    claim_id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=1000)
    evidence_id: str = Field(min_length=1, max_length=160)
    supporting_quote: str = Field(min_length=1, max_length=2500)

class Draft(Contract):
    claims: list[Claim] = Field(min_length=1, max_length=6)
    missing_evidence: list[str] = Field(default_factory=list, max_length=12)
    routing_recommendation: Literal['REFER_TO_COMMITTEE'] = 'REFER_TO_COMMITTEE'
    reasons: list[str] = Field(default_factory=list, max_length=6)

class Verdict(Contract):
    claim_id: str
    supported: bool
    reason: str = Field(min_length=1, max_length=1000)

class Review(Contract):
    verdicts: list[Verdict] = Field(min_length=1, max_length=6)
    needs_research: bool
    research_query: str = Field(default='', max_length=1500)

class SearchArgs(Contract):
    query: str = Field(min_length=1, max_length=3000)

class FetchArgs(Contract):
    clause_id: str = Field(min_length=1, max_length=100)

class QuoteArgs(Contract):
    evidence_id: str = Field(min_length=1, max_length=160)
    quote: str = Field(min_length=1, max_length=2500)

class QuoteBatch(Contract):
    quotes: list[QuoteArgs] = Field(min_length=1, max_length=6)

ARGUMENTS = {'search_regulations': SearchArgs, 'fetch_exact_clause': FetchArgs, 'verify_claim_quotes': QuoteBatch}
DESCRIPTIONS = {
    'search_regulations': 'Search base and modifying handbook provisions. Returns evidence IDs, exact quotes and citation metadata.',
    'fetch_exact_clause': 'Fetch a complete reviewed clause by its locator, preserving source metadata.',
    'verify_claim_quotes': 'Check up to six exact quotes against canonical sources. This checks quote presence, not claim entailment.',
}
SCHEMAS = [{'type': 'function', 'function': {'name': name, 'description': DESCRIPTIONS[name],
             'parameters': model.model_json_schema()}} for name, model in ARGUMENTS.items()]

def normalize(text):
    return ' '.join(text.split())

class EvidenceTools:
    def __init__(self, search=None, fetch=None, quote_check=None):
        from retrieval import search_regulations, fetch_exact_clause, verify_source_quote
        self.search = search or search_regulations.invoke
        self.fetch = fetch or fetch_exact_clause.invoke
        self.quote_check = quote_check or verify_source_quote.invoke
        self.bank = {}
        self.checked = set()

    def _collect(self, result):
        citations = list(result.get('citations', []))
        citations.extend(c for p in result.get('passages', []) for c in p.get('citations', []))
        reviewed = [c for c in citations if c.get('citation_metadata_verified')]
        for c in reviewed:
            self.bank[c['evidence_id']] = c
        # Omit duplicated page context to conserve the free tier's token allowance.
        return {'status': result.get('status'), 'citations': reviewed}

    def execute(self, name, arguments):
        if name not in ARGUMENTS:
            raise AgentFailure('Model selected a tool outside the allowlist.')
        args = ARGUMENTS[name].model_validate(arguments)
        if name == 'search_regulations':
            return self._collect(json.loads(self.search(args.model_dump())))
        if name == 'fetch_exact_clause':
            return self._collect(json.loads(self.fetch(args.model_dump())))
        results = []
        for item in args.quotes:
            known = self.bank.get(item.evidence_id)
            if not known or normalize(item.quote) not in normalize(known['exact_quote']):
                supported = False
            else:
                supported = json.loads(self.quote_check(item.model_dump())).get('quote_supported') is True
            if supported:
                self.checked.add((item.evidence_id, normalize(item.quote)))
            results.append({'evidence_id': item.evidence_id, 'quote_supported': supported})
        return {'results': results, 'semantic_entailment_checked': False}

def role_loop(model, role, payload, output_type, tools, metrics):
    started = time.monotonic()
    entry = {'agent': role, 'prompt_version': f'{role}_v1', 'model_calls': 0,
             'tool_calls': 0, 'tools_used': [], 'success': False}
    metrics.append(entry)
    prompt = (ROOT / 'prompts' / f'{role}_v1.txt').read_text(encoding='utf-8-sig')
    messages = [{'role': 'system', 'content': prompt + '\nOutput JSON schema:\n' + json.dumps(output_type.model_json_schema())},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    try:
        for _ in range(MAX_TURNS):
            entry['model_calls'] += 1
            message = model.complete(role, messages, SCHEMAS)
            calls = message.get('tool_calls', [])
            if not calls:
                result = output_type.model_validate_json(message.get('content') or '')
                if role == 'investigator' and 'search_regulations' not in entry['tools_used']:
                    raise AgentFailure('Investigator did not select the retrieval tool.')
                entry['success'] = True
                return result
            if len(calls) + entry['tool_calls'] > MAX_TOOLS:
                raise AgentFailure('Agent tool-call budget exhausted.')
            ids = [call.get('id') for call in calls]
            if not all(ids) or len(set(ids)) != len(ids):
                raise AgentFailure('Invalid or duplicate tool call IDs.')
            messages.append(message)
            for call in calls:
                name = call['function']['name']
                entry['tool_calls'] += 1
                entry['tools_used'].append(name)
                result = tools.execute(name, json.loads(call['function']['arguments']))
                content = json.dumps(result, ensure_ascii=False)
                if len(content) > 45000:
                    raise AgentFailure('Tool result exceeded the context budget.')
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': content})
        raise AgentFailure('Agent model-call budget exhausted.')
    finally:
        entry['latency_seconds'] = round(time.monotonic() - started, 4)

class AgentState(TypedDict, total=False):
    petition: str
    passes: int
    query: str
    draft: dict
    review: dict
    status: str
    errors: list[str]
    metrics: list[dict]


def run_agents(petition, model, tools=None):
    request = PetitionRequest(petition=petition)
    tools = tools or EvidenceTools()
    metrics = []

    def investigate(state):
        tools.checked.clear()
        draft = role_loop(model, 'investigator', {'petition': state['petition'],
                          'research_query': state.get('query', '')}, Draft, tools, metrics)
        ids = [c.claim_id for c in draft.claims]
        if len(set(ids)) != len(ids):
            raise AgentFailure('Duplicate draft claim IDs.')
        for claim in draft.claims:
            evidence = tools.bank.get(claim.evidence_id)
            if not evidence or normalize(claim.supporting_quote) not in normalize(evidence['exact_quote']):
                raise AgentFailure('Investigator cited an unknown or mismatched quote.')
        return {'draft': draft.model_dump(), 'passes': state.get('passes', 0) + 1}

    def verify(state):
        tools.checked.clear()
        draft = Draft.model_validate(state['draft'])
        # New conversation: only petition, typed handoff and canonical evidence are shared.
        selected = {c.evidence_id: tools.bank[c.evidence_id] for c in draft.claims}
        review = role_loop(model, 'verifier', {'petition': state['petition'], 'draft': draft.model_dump(),
                           'evidence': selected}, Review, tools, metrics)
        claim_ids = {c.claim_id for c in draft.claims}
        verdict_ids = [v.claim_id for v in review.verdicts]
        if len(set(verdict_ids)) != len(verdict_ids) or set(verdict_ids) != claim_ids:
            raise AgentFailure('Verifier omitted, duplicated or invented claim verdicts.')
        if any((c.evidence_id, normalize(c.supporting_quote)) not in tools.checked for c in draft.claims):
            raise AgentFailure('Verifier did not check every supporting quote using its tool.')
        supported = all(v.supported for v in review.verdicts) and not review.needs_research
        status = 'REVIEW_REQUIRED' if supported else ('RETRY' if state['passes'] < MAX_PASSES else 'ESCALATE')
        return {'review': review.model_dump(), 'status': status, 'query': review.research_query}

    graph = StateGraph(AgentState)
    graph.add_node('investigate', investigate)
    graph.add_node('verify', verify)
    graph.add_edge(START, 'investigate')
    graph.add_edge('investigate', 'verify')
    graph.add_conditional_edges('verify', lambda s: 'investigate' if s['status'] == 'RETRY' else 'finish',
                                {'investigate': 'investigate', 'finish': END})
    try:
        result = graph.compile().invoke({'petition': request.petition, 'passes': 0}, config={'recursion_limit': 10})
        if result['status'] != 'REVIEW_REQUIRED':
            result['draft']['claims'] = []
        else:
            # Canonical metadata, never model-supplied citation locations.
            for claim in result['draft']['claims']:
                claim['citation'] = tools.bank[claim['evidence_id']]
        result.update(mode='HOSTED_AGENTS', metrics=metrics, model_usage=getattr(model, 'events', []),
                      human_review_required=True, final_decision_made=False,
                      semantic_review='LLM_JUDGMENT_NOT_PROOF', provider_response_used=isinstance(model, HostedChat))
        return result
    except Exception as exc:
        if metrics:
            metrics[-1]['success'] = False
        # No unverifiable generated claims survive; preserve the deterministic core as fallback.
        from workflow import run_petition
        result = run_petition(request.petition)
        result.update(mode='DETERMINISTIC_FALLBACK', hosted_failure=type(exc).__name__,
                      metrics=metrics, model_usage=getattr(model, 'events', []),
                      human_review_required=True, final_decision_made=False)
        return result


def run_hosted(petition):
    request = PetitionRequest(petition=petition)
    model = None
    try:
        model = HostedChat(HostedSettings.from_env())
        return run_agents(request.petition, model)
    except ModelUnavailable:
        from workflow import run_petition
        result = run_petition(request.petition)
        result.update(mode='DETERMINISTIC_FALLBACK', hosted_failure='MODEL_CONFIGURATION_UNAVAILABLE')
        return result
    finally:
        if model is not None:
            model.close()

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--petition', default='My attendance is 72% due to illness. What are the medical condonation requirements?')
    result = run_hosted(parser.parse_args().petition)
    print(json.dumps({k: v for k, v in result.items() if k != 'evidence'}, ensure_ascii=False, indent=2))
