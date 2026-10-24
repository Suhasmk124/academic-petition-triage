"""Limited deterministic safeguards, not a complete injection/toxicity classifier."""
import re
import unicodedata
from typing import Literal
from pydantic import Field, StrictInt
from assessment import Contract

VERSION = 'rules-v1'


class AgentMetric(Contract):
    agent: Literal['investigator', 'verifier']
    prompt_version: str = Field(pattern=r'^(investigator|verifier)_v[0-9]+$')
    model_calls: StrictInt = Field(ge=0, le=6)
    retries: StrictInt = Field(default=0,ge=0,le=6)
    tool_calls: StrictInt = Field(ge=0, le=6)
    tools_used: list[Literal['search_regulations', 'fetch_exact_clause', 'verify_claim_quotes']] = Field(max_length=6)
    success: bool
    latency_seconds: float = Field(ge=0, allow_inf_nan=False)


class PolicyViolation(ValueError):
    def __init__(self, reasons):
        self.reasons = reasons
        super().__init__('Content requires a safe resubmission')


def normalized(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return ' '.join(''.join(c for c in text if unicodedata.category(c) != 'Cf').split())


RULES = {
    'INSTRUCTION_OVERRIDE': r'\b(?:ignore|disregard|override|forget)\b.{0,60}\b(?:instructions?|prompts?|rules?|safeguards?|polic(?:y|ies))\b',
    'ROLE_SPOOFING': r'(?:<\|(?:im_start|im_end|system|assistant)\|>|\[/?inst\]|</?(?:system|developer|assistant)>|(?:^|\s)(?:system|developer)\s*:)',
    'SECRET_REQUEST': r'\b(?:reveal|print|show|dump|expose|send|read)\b.{0,60}(?:\b(?:api[ _-]?keys?|secrets?|credentials?|system prompt|environment variables)\b|\.env\b)',
    'EXECUTION_REQUEST': r'\b(?:execute|run)\b.{0,30}\b(?:powershell|shell commands?|python code|curl|subprocess)\b',
    'VERIFICATION_BYPASS': r'\b(?:skip|bypass|disable)\b.{0,40}\b(?:verif\w*|citation\w*|source checks?|human review)\b',
    'TOXIC_LANGUAGE': r'\b(?:idiot|moron|stupid|fuck(?:ing)?|shithead)\b|\b(?:kill yourself|you deserve to die)\b',
}


def content_flags(text):
    value = normalized(text)
    return [name for name, pattern in RULES.items() if re.search(pattern, value)]


def check_input(text):
    flags = content_flags(text)
    if flags:
        raise PolicyViolation(flags)


def guarded_result(result, petition=None):
    """Fail closed at the local service boundary; retain only validated contract fields.

    Local modes are extractive, so a paraphrase is rejected even if it may be true.
    Canonical clauses are reconstructed from reviewed source anchors, independent of
    returned citation metadata. General semantic entailment is deliberately not claimed.
    """
    from assessment import Assessment, Finding, PROVISIONS, classify, verify_findings
    from index_corpus import reviewed
    from retrieval import source_pages, validate_record
    errors = []
    try:
        if not isinstance(result, dict) or result.get('status') not in ('REVIEW_REQUIRED', 'ESCALATE'):
            raise ValueError('Invalid result envelope')
        brief = result.get('draft') or result.get('assessment')
        if not isinstance(brief, dict) or brief.get('routing_recommendation') != 'REFER_TO_COMMITTEE':
            raise ValueError('Invalid review route')
        for key, expected in [('human_review_required', True), ('final_decision_made', False)]:
            if result.get(key, brief.get(key)) is not expected or (key in brief and brief[key] is not expected):
                raise ValueError('Human decision boundary violated')
        raw = brief.get('claims', brief.get('findings', []))
        if not isinstance(raw, list) or len(raw) > 6:
            raise ValueError('Invalid findings')
        if result['status'] == 'ESCALATE' and raw:
            raise ValueError('Escalated output contains findings')
        if result['status'] == 'REVIEW_REQUIRED':
            findings = [Finding(finding_id=item.get('claim_id', item.get('finding_id', '')),
                                evidence_id=item['evidence_id'], statement=item['statement'],
                                supporting_quote=item['supporting_quote'], citation=item['citation']) for item in raw]
            records = {record['id']: record for record in reviewed(source_pages())}
            verification = verify_findings(findings, records, validate_record)
            if not verification.passed:
                raise ValueError('Canonical source verification failed')
            if petition is not None:
                expected = set(PROVISIONS[classify(petition)])
                if not expected or {item.citation['clause_id'] for item in findings} != expected:
                    raise ValueError('Incomplete pilot provision set')
            if len({item.evidence_id for item in findings}) != len(findings):
                raise ValueError('Duplicate evidence')
        texts = brief.get('missing_evidence', []) + brief.get('reasons', [])
        if not isinstance(texts, list) or len(texts) > 20 or any(not isinstance(text, str) or len(text) > 1500 for text in texts):
            raise ValueError('Invalid explanatory text')
        if any(content_flags(text) for text in texts):
            raise ValueError('Unsafe explanatory text')
        # Whitelist the handoff. Raw petitions, arbitrary model fields, diagnostics
        # and tool payloads cannot leak through the service result.
        if 'assessment' in result and 'draft' not in result:
            brief = Assessment.model_validate(brief).model_dump()
        else:
            brief = {key: brief[key] for key in ('claims', 'missing_evidence', 'routing_recommendation', 'reasons') if key in brief}
            brief['claims'] = [{key: item[key] for key in ('claim_id', 'evidence_id', 'statement', 'supporting_quote', 'citation')} for item in raw]
        output = {key: result[key] for key in ('status', 'mode', 'simulated', 'stub_workflow_path', 'billable_model_requests',
                                              'provider_response_used', 'semantic_review') if key in result}
        output['draft' if 'draft' in result else 'assessment'] = brief
        metrics = result.get('metrics', [])
        if not isinstance(metrics, list) or len(metrics) > 4:
            raise ValueError('Invalid agent metrics')
        output['metrics'] = [AgentMetric.model_validate(entry).model_dump() for entry in metrics]
        output['usage'] = []
        for event in result.get('model_usage',[])[:48]:
            if event.get('agent') not in ('investigator','verifier'): continue
            usage = {'agent':event['agent'], 'estimated':bool(event.get('estimated',False))}
            for key in ('input_tokens','output_tokens'):
                value = event.get(key)
                usage[key] = value if isinstance(value,int) and 0<=value<=1000000 else None
            usage['billed_cost_usd'] = 0.0 if result.get('mode')=='STUB' else event.get('billed_cost_usd')
            output['usage'].append(usage)
        output.update(human_review_required=True, final_decision_made=False,
                      safety={'version': VERSION, 'input': 'passed', 'output': 'passed'})
        return output
    except (ValueError, KeyError, TypeError, AttributeError):
        errors.append('OUTPUT_CONTRACT_OR_SOURCE_CHECK_FAILED')
    return dict(status='ESCALATE', mode='SAFE_FALLBACK', human_review_required=True, final_decision_made=False,
                billable_model_requests=0, provider_response_used=False,
                assessment=Assessment(petition_type='UNSUPPORTED', reasons=['The output did not pass the final safety and source checks. Human officer review is required.']).model_dump(),
                safety={'version': VERSION, 'input': 'passed', 'output': 'blocked', 'reasons': errors})
