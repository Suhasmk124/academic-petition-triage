"""Two separately prompted LLM roles in LangGraph, with bounded model/tool calls."""
import argparse
import json
import sys
import time
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Literal, TypedDict
from pydantic import Field, ValidationError
from langgraph.graph import StateGraph, START, END
from assessment import Contract, PetitionRequest
from hosted_model import HostedChat, HostedSettings, ModelUnavailable

ROOT = Path(__file__).resolve().parents[1]
MAX_TURNS = 6
MAX_TOOLS = 6
MAX_PASSES = 2
PROMPT_VERSIONS = {'investigator': 'v2', 'verifier': 'v3'}
PROMPT_VARIANTS = {'baseline':PROMPT_VERSIONS, 'strict':{'investigator':'v5','verifier':'v6'}}
PROMPT_CONTEXT = ContextVar('prompt_versions',default=PROMPT_VERSIONS)
STRICT_TOOLS = {'investigator': {'search_regulations', 'fetch_exact_clause'}, 'verifier': {'verify_claim_quotes'}}

class AgentFailure(RuntimeError):
    pass

class ClaimReference(Contract):
    claim_id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=1000)
    evidence_id: str = Field(min_length=1, max_length=160)

class Claim(ClaimReference):
    supporting_quote: str = Field(min_length=1, max_length=2500)

class Draft(Contract):
    claims: list[Claim] = Field(min_length=1, max_length=6)
    missing_evidence: list[str] = Field(default_factory=list, max_length=12)
    routing_recommendation: Literal['REFER_TO_COMMITTEE'] = 'REFER_TO_COMMITTEE'
    reasons: list[str] = Field(default_factory=list, max_length=6)

class InvestigationDraft(Draft):
    claims: list[ClaimReference] = Field(min_length=1, max_length=6)

class SourceSelection(Contract):
    claim_id: str = Field(min_length=1,max_length=80)
    evidence_id: str = Field(min_length=1,max_length=160)

class InvestigationSelection(Contract):
    claims: list[SourceSelection] = Field(min_length=1,max_length=6)
    missing_evidence: list[str] = Field(default_factory=list,max_length=12)
    routing_recommendation: Literal['REFER_TO_COMMITTEE'] = 'REFER_TO_COMMITTEE'
    reasons: list[str] = Field(default_factory=list,max_length=6)

class Verdict(Contract):
    claim_id: str
    supported: bool
    reason: str = Field(min_length=1, max_length=1000)

class Review(Contract):
    verdicts: list[Verdict] = Field(min_length=1, max_length=6)
    needs_research: bool
    research_query: str = Field(default='', max_length=1500)

class VerdictDecision(Contract):
    claim_id: str = Field(min_length=1,max_length=80)
    supported: bool

class ReviewDecision(Contract):
    verdicts: list[VerdictDecision] = Field(min_length=1,max_length=6)
    needs_research: bool
    research_query: str = Field(default='',max_length=1500)

class SearchArgs(Contract):
    query: str = Field(min_length=1, max_length=3000)

class FetchArgs(Contract):
    clause_id: str = Field(min_length=1, max_length=100)

class QuoteArgs(Contract):
    evidence_id: str = Field(min_length=1, max_length=160)
    quote: str = Field(min_length=1, max_length=2500)

class QuoteBatch(Contract):
    evidence_ids: list[str] = Field(min_length=1, max_length=6)

ARGUMENTS = {'search_regulations': SearchArgs, 'fetch_exact_clause': FetchArgs, 'verify_claim_quotes': QuoteBatch}
DESCRIPTIONS = {
    'search_regulations': 'Search base and modifying handbook provisions. Returns evidence IDs, exact quotes and citation metadata.',
    'fetch_exact_clause': 'Fetch a complete reviewed clause by its locator, preserving source metadata.',
    'verify_claim_quotes': 'Check up to six exact quotes against canonical sources. This checks quote presence, not claim entailment.',
}
def inline_schema(schema):
    """Expand nested references so hosted tools see each argument's field names."""
    definitions = schema.get('$defs', {})
    def expand(value):
        if isinstance(value, dict):
            if '$ref' in value:
                return expand(definitions[value['$ref'].split('/')[-1]])
            return {key: expand(item) for key, item in value.items() if key != '$defs'}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value
    return expand(schema)

SCHEMAS = [{'type': 'function', 'function': {'name': name, 'description': DESCRIPTIONS[name],
             'parameters': inline_schema(model.model_json_schema())}} for name, model in ARGUMENTS.items()]

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
        self.attempted = set()

    def _collect(self, result):
        citations = list(result.get('citations', []))
        citations.extend(c for p in result.get('passages', []) for c in p.get('citations', []))
        reviewed = [c for c in citations if c.get('citation_metadata_verified')]
        for c in reviewed:
            from safety import check_input
            check_input(c['exact_quote'])
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
        for evidence_id in args.evidence_ids:
            self.attempted.add(evidence_id)
            known = self.bank.get(evidence_id)
            supported = bool(known) and json.loads(self.quote_check({'evidence_id': evidence_id, 'quote': known['exact_quote']})).get('quote_supported') is True
            if supported:
                self.checked.add((evidence_id, normalize(known['exact_quote'])))
            results.append({'evidence_id': evidence_id, 'quote_supported': supported})
        return {'results': results, 'semantic_entailment_checked': False}

def role_loop(model, role, payload, output_type, tools, metrics):
    from telemetry import span
    with span('agent.'+role,agent=role,prompt_version=role+'_'+PROMPT_CONTEXT.get()[role]) as current:
        try:
            return _role_loop(model,role,payload,output_type,tools,metrics)
        finally:
            if metrics:
                for key in ('model_calls','tool_calls','success','latency_seconds'):
                    current.set_attribute('agent.'+key,metrics[-1].get(key,0))


def _role_loop(model, role, payload, output_type, tools, metrics):
    started = time.monotonic()
    entry = {'agent': role, 'prompt_version': f'{role}_{PROMPT_CONTEXT.get()[role]}', 'model_calls': 0,
             'tool_calls': 0, 'tools_used': [], 'success': False}
    usage_start=len(getattr(model,'events',[]))
    metrics.append(entry)
    prompt = (ROOT / 'prompts' / f'{role}_{PROMPT_CONTEXT.get()[role]}.txt').read_text(encoding='utf-8-sig')
    messages = [{'role': 'system', 'content': prompt + '\nWhen finished, call submit_result with your final structured result. It is an output channel, not a source tool. Use the required source tool first.\nOutput schema:\n' + json.dumps(inline_schema(output_type.model_json_schema()))},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    allowed = STRICT_TOOLS[role] if PROMPT_CONTEXT.get()['verifier'] == 'v6' else ARGUMENTS
    schemas=[schema for schema in SCHEMAS if schema['function']['name'] in allowed]+[{'type':'function','function':{'name':'submit_result','description':'Submit the final structured role result after required source tools.',
                                                  'parameters':inline_schema(output_type.model_json_schema())}}]
    required_tool='search_regulations' if role=='investigator' else 'verify_claim_quotes'
    repaired_provider_format=False
    try:
        for _ in range(MAX_TURNS):
            entry['model_calls'] += 1
            try:
                message = model.complete(role, messages, [] if repaired_provider_format else schemas)
            except ModelUnavailable as exc:
                if exc.code != 'TOOL_FORMAT_REJECTED' or repaired_provider_format or required_tool not in entry['tools_used']:
                    raise
                repaired_provider_format=True
                messages.append({'role':'user','content':'Your last response could not be parsed. Return only the final JSON object as plain text, without markup or any tool call.'})
                continue
            calls = message.get('tool_calls', [])
            if len(calls)==1 and calls[0].get('function',{}).get('name') in ('submit_result','JSON'):
                try:
                    result=output_type.model_validate_json(calls[0]['function']['arguments'])
                except ValidationError as exc:
                    messages.append(message)
                    messages.append({'role':'tool','tool_call_id':calls[0]['id'],'content':json.dumps({'error':'Final result does not match the supplied schema. Correct it within the existing budget.',
                        'fields':[{'path':list(item['loc']),'type':item['type']} for item in exc.errors(include_input=False,include_url=False)]})})
                    continue
                required_tool='search_regulations' if role=='investigator' else 'verify_claim_quotes'
                if required_tool in entry['tools_used']:
                    entry['success']=True
                    return result
                messages.append(message)
                messages.append({'role':'tool','tool_call_id':calls[0]['id'],'content':json.dumps({'error':f'Call {required_tool} first. No source work has been completed.'})})
                continue
            if not calls:
                try:
                    result = output_type.model_validate_json(message.get('content') or '')
                except ValidationError as exc:
                    messages.append(message)
                    messages.append({'role':'user','content':json.dumps({'error':'Final result does not match the supplied schema. Call submit_result with every required field. Existing call limits still apply.',
                        'fields':[{'path':list(item['loc']),'type':item['type']} for item in exc.errors(include_input=False,include_url=False)]})})
                    continue
                required_tool='search_regulations' if role=='investigator' else 'verify_claim_quotes'
                if required_tool not in entry['tools_used']:
                    messages.append(message)
                    messages.append({'role':'user','content':f'Your role is incomplete. You must choose and call {required_tool} before returning the final JSON. Use the supplied arguments and evidence IDs. This reminder does not increase your call budget.'})
                    continue
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
                if name not in allowed:
                    raise AgentFailure('Model selected a tool outside its role allowlist.')
                entry['tool_calls'] += 1
                entry['tools_used'].append(name)
                from telemetry import span
                with span('tool.'+(name if name in ARGUMENTS else 'invalid')):
                    result = tools.execute(name, json.loads(call['function']['arguments']))
                content = json.dumps(result, ensure_ascii=False)
                if len(content) > 45000:
                    raise AgentFailure('Tool result exceeded the context budget.')
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': content})
        raise AgentFailure('Agent model-call budget exhausted.')
    finally:
        entry['retries']=sum(1 for event in getattr(model,'events',[])[usage_start:] if event.get('attempt',1)>1)
        entry['latency_seconds'] = round(time.monotonic() - started, 4)

def critical_detail_errors(draft, bank):
    """Narrow source-specific guards, not a general semantic entailment checker."""
    errors = {}
    for claim in draft.claims:
        locator = bank.get(claim.evidence_id, {}).get('clause_id', '')
        text = claim.statement.lower()
        if locator == '8.1(iii)' and 'portal' in text and 'sap' in text and 'slcm' not in text:
            errors[claim.claim_id] = 'The application clause names SLCM; SAP is named for document upload. Preserve that distinction.'
        if locator == '8.1(ii)' and ('or iisc' in text or ('issued' in text and 'cmo' not in text and 'chief medical officer' not in text)):
            errors[claim.claim_id] = 'The certificate issuer must preserve the CMO, Health Centre, IISc requirement; do not introduce alternative issuers.'
    return errors

class AgentState(TypedDict, total=False):
    petition: str
    passes: int
    query: str
    draft: dict
    review: dict
    status: str
    errors: list[str]
    metrics: list[dict]
    agent_handoff: list[dict]


def run_agents(petition, model, tools=None, variant=None):
    variant = variant or os.getenv('TRIAGE_PROMPT_VARIANT','baseline')
    if variant not in PROMPT_VARIANTS: raise ValueError('Unknown prompt variant')
    token = PROMPT_CONTEXT.set(PROMPT_VARIANTS[variant])
    try:
        return _run_agents(petition,model,tools)
    finally:
        PROMPT_CONTEXT.reset(token)


def _run_agents(petition, model, tools=None):
    request = PetitionRequest(petition=petition)
    from safety import check_input
    check_input(request.petition)
    tools = tools or EvidenceTools()
    metrics = []
    from assessment import PROVISIONS, classify
    required = PROVISIONS[classify(request.petition)]
    strict = PROMPT_CONTEXT.get()['verifier'] == 'v6'

    def investigate(state):
        tools.checked.clear()
        selection_mode = strict
        if strict:
            tools.bank.clear()
        draft = role_loop(model, 'investigator', {'petition': state['petition'],
                          'required_provisions':required,
                          'research_query': state.get('query', '')}, InvestigationSelection if selection_mode else InvestigationDraft, tools, metrics)
        ids = [c.claim_id for c in draft.claims]
        if len(set(ids)) != len(ids):
            raise AgentFailure('Duplicate draft claim IDs.')
        for claim in draft.claims:
            evidence = tools.bank.get(claim.evidence_id)
            if not evidence:
                raise AgentFailure('Investigator cited an unknown evidence ID.')
        draft = Draft(**(draft.model_dump() | {'claims': [claim.model_dump() | {'supporting_quote': tools.bank[claim.evidence_id]['exact_quote']} |
                       ({'statement':tools.bank[claim.evidence_id]['exact_quote']} if selection_mode else {}) for claim in draft.claims]}))
        return {'draft': draft.model_dump(), 'passes': state.get('passes', 0) + 1}

    def verify(state):
        tools.checked.clear()
        tools.attempted.clear()
        draft = Draft.model_validate(state['draft'])
        # New conversation: only petition, typed handoff and canonical evidence are shared.
        selected = {c.evidence_id: tools.bank[c.evidence_id] for c in draft.claims}
        payload = {'petition': state['petition'], 'quote_check_arguments': {'evidence_ids': list(selected)}}
        if strict:
            payload.update(required_provisions=required, claims=[
                {'claim_id': claim.claim_id, 'evidence_id': claim.evidence_id,
                 'clause_id': selected[claim.evidence_id]['clause_id'],
                 'quote': claim.supporting_quote} for claim in draft.claims])
        else:
            payload.update(draft=draft.model_dump(), evidence=selected)
        review = role_loop(model, 'verifier', payload, ReviewDecision if strict else Review, tools, metrics)
        if isinstance(review,ReviewDecision):
            review=Review(**(review.model_dump() | {'verdicts':[item.model_dump() | {'reason':'Verifier accepted this clause after the source audit.' if item.supported else 'Verifier flagged this clause for further research.'} for item in review.verdicts]}))
        claim_ids = {c.claim_id for c in draft.claims}
        verdict_ids = [v.claim_id for v in review.verdicts]
        if len(set(verdict_ids)) != len(verdict_ids) or set(verdict_ids) != claim_ids:
            raise AgentFailure('Verifier omitted, duplicated or invented claim verdicts.')
        if not set(selected).issubset(tools.attempted):
            raise AgentFailure('Verifier did not check every supporting quote using its tool.')
        failed_checks = {c.claim_id for c in draft.claims
                         if (c.evidence_id, normalize(c.supporting_quote)) not in tools.checked}
        if failed_checks and not strict:
            raise AgentFailure('Verifier did not check every supporting quote using its tool.')
        detail_errors = critical_detail_errors(draft, tools.bank)
        missing = []
        selected_clauses = []
        if strict:
            selected_clauses = [selected[c.evidence_id]['clause_id'] for c in draft.claims]
            missing = [clause for clause in required if clause not in selected_clauses]
            for claim in draft.claims:
                locator = selected[claim.evidence_id]['clause_id']
                if claim.claim_id in failed_checks:
                    detail_errors[claim.claim_id] = 'The quotation did not pass the canonical source check.'
                elif locator not in required or selected_clauses.count(locator) > 1:
                    detail_errors[claim.claim_id] = 'The clause is outside the required set or was selected more than once.'
        if detail_errors:
            for verdict in review.verdicts:
                if verdict.claim_id in detail_errors:
                    verdict.supported = False
                    verdict.reason = detail_errors[verdict.claim_id]
            review.needs_research = True
            if not strict:
                review.research_query = 'Retrieve exact attendance medical provisions; preserve SLCM application, SAP upload and CMO certificate issuer requirements.'
        if missing:
            review.needs_research = True
        supported = all(v.supported for v in review.verdicts) and not review.needs_research
        status = 'REVIEW_REQUIRED' if supported else ('RETRY' if state['passes'] < MAX_PASSES else 'ESCALATE')
        update = {'review': review.model_dump(), 'status': status, 'query': review.research_query}
        if strict:
            rejected_ids = {v.claim_id for v in review.verdicts if not v.supported}
            rejected_clauses = [selected[c.evidence_id]['clause_id'] for c in draft.claims if c.claim_id in rejected_ids]
            focus = [clause for clause in required if clause in missing or clause in rejected_clauses]
            update['query'] = f"{state['petition'][:2700]} Verify required provisions {', '.join(focus or required)}." if status == 'RETRY' else ''
            update['agent_handoff'] = [*state.get('agent_handoff', []), {
                'selected': len(draft.claims), 'checked': len(draft.claims) - len(failed_checks),
                'missing': missing, 'rejected': len(rejected_ids), 'outcome': status}]
        return update

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
                      hosted_failure_code=exc.code if isinstance(exc,ModelUnavailable) else 'AGENT_CONTRACT_FAILED',
                      hosted_failure_reason=str(exc) if isinstance(exc, (AgentFailure, ModelUnavailable)) else 'Model output did not meet the validated contract.',
                      metrics=metrics, model_usage=getattr(model, 'events', []),
                      human_review_required=True, final_decision_made=False)
        return result


def run_hosted(petition):
    request = PetitionRequest(petition=petition)
    from safety import check_input
    check_input(request.petition)
    model = None
    try:
        model = HostedChat(HostedSettings.from_env())
        return run_agents(request.petition, model)
    except ModelUnavailable:
        from workflow import run_petition
        result = run_petition(request.petition)
        result.update(mode='DETERMINISTIC_FALLBACK', hosted_failure='MODEL_CONFIGURATION_UNAVAILABLE', hosted_failure_code='CONFIGURATION_UNAVAILABLE')
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
