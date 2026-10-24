"""Typed extractive assessments. No LLM or final academic decisions."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')

class PetitionRequest(Contract):
    petition: str = Field(min_length=1, max_length=4000)

    @field_validator('petition')
    @classmethod
    def clean_petition(cls, value):
        if not value.strip():
            raise ValueError('Petition cannot be blank')
        return value.strip()

class Finding(Contract):
    finding_id: str
    evidence_id: str
    statement: str
    supporting_quote: str
    citation: dict
    kind: Literal['EXTRACTIVE_RULE'] = 'EXTRACTIVE_RULE'

class Verification(Contract):
    passed: bool
    mode: Literal['EXTRACTIVE_SOURCE_MATCH'] = 'EXTRACTIVE_SOURCE_MATCH'
    checked_findings: int = 0
    errors: list[str] = Field(default_factory=list)
    semantic_entailment_checked: Literal[False] = False

class Assessment(Contract):
    petition_type: Literal['ATTENDANCE', 'TERMINAL_MEDICAL', 'X_GRADE', 'UNSUPPORTED']
    findings: list[Finding] = Field(default_factory=list)
    missing_provisions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    routing_recommendation: Literal['GRANT_UNDER_PROVISION', 'REFER_TO_COMMITTEE', 'REJECT_UNDER_PROVISION'] = 'REFER_TO_COMMITTEE'
    reasons: list[str] = Field(default_factory=list)
    human_review_required: Literal[True] = True
    final_decision_made: Literal[False] = False

def classify(petition):
    """Narrow keyword classifier for this pilot; other types escalate."""
    text = petition.lower()
    # Mixed or explicitly external requests require a human scope check. Do not
    # let one keyword turn a refund, employment or another-institution case into
    # a supported handbook assessment.
    outside = ('parking ticket','parking refund','scholarship payment','hostel room','tuition refund',
               'transcript','visa application','employee attendance','office attendance','work attendance',
               'school attendance','another university','different college','another college','different university')
    if any(phrase in text for phrase in outside):
        return 'UNSUPPORTED'
    if 'attendance' in text or 'missed classes' in text:
        return 'ATTENDANCE'
    if any(word in text for word in ('x grade', "'x' grade", '‘x’ grade', 'retest')):
        return 'X_GRADE'
    if any(word in text for word in ('medical', 'illness', 'sick')) and any(word in text for word in ('terminal exam', 'final exam', 'missed exam')):
        return 'TERMINAL_MEDICAL'
    return 'UNSUPPORTED'

PROVISIONS = {
    'ATTENDANCE': ['8.1(i)', '8.1(ii)', '8.1(iii)'],
    'TERMINAL_MEDICAL': ['5.6(i)'] + [f'5.7(C)({i})' for i in range(1, 6)],
    'X_GRADE': [f'5.7(C)({i})' for i in range(1, 6)],
    'UNSUPPORTED': [],
}
MISSING_EVIDENCE = {
    'ATTENDANCE': ['Official course attendance record and examination/semester concerned.',
                   'Medical leave dates, recovery date and SLCM submission timestamp.',
                   'CMO/Health Centre certificate and confirmation of the SAP upload.',
                   'Human officer confirmation of applicable condonation and authority.'],
    'TERMINAL_MEDICAL': ['Examination, course, term and reason/date of absence.',
                         'Recovery date, SLCM submission timestamp and supporting SAP upload.',
                         'CMO certification and instructor/Academics Section documentation.',
                         'Result declaration date, retest schedule and certified extension justification, if any.'],
    'X_GRADE': ['Course, registered term, result date and current grade record.',
                'CMO-attested medical evidence and instructor documentation.',
                'Retest date and any additional certified medical justification.'],
    'UNSUPPORTED': ['Applicable authoritative provision and human officer review.'],
}

def build_assessment(petition, evidence):
    kind = classify(petition)
    expected = PROVISIONS[kind]
    citations = {}
    for passage in evidence.get('passages', [])[:4]:
        for item in passage.get('citations', [])[:16]:
            if item.get('citation_metadata_verified') and item.get('clause_id') in expected:
                citations.setdefault(item['clause_id'], item)
    findings = []
    for locator in expected:
        if locator in citations:
            item = citations[locator]
            findings.append(Finding(finding_id=f'finding-{len(findings) + 1}',
                                    evidence_id=item['evidence_id'], statement=item['exact_quote'],
                                    supporting_quote=item['exact_quote'], citation=item))
    return Assessment(petition_type=kind, findings=findings,
                      missing_provisions=[x for x in expected if x not in citations],
                      missing_evidence=MISSING_EVIDENCE[kind],
                      reasons=['Confirm that the IISc Undergraduate Handbook 2025-26 applies to this case.',
                               'Petition statements are unverified; supporting records have not been reviewed.',
                               'This pilot supplies cited rules for human review and does not determine eligibility.'])

def verify_findings(findings, canonical_records, check_source):
    """Bind every extractive statement and citation to its canonical source record."""
    from retrieval import citation, normal
    errors = []
    for finding in findings:
        record = canonical_records.get(finding.evidence_id)
        if record is None:
            errors.append(f'{finding.finding_id}: unknown evidence ID')
            continue
        try:
            check_source(record)
            if not record['metadata'].get('citation_metadata_verified'):
                raise ValueError('Clause metadata has not been reviewed')
            if finding.citation != citation(record):
                raise ValueError('Citation metadata or quote differs from canonical evidence')
            if not normal(finding.supporting_quote) or normal(finding.supporting_quote) not in normal(record['text']):
                raise ValueError('Quote is absent from canonical evidence')
            if normal(finding.statement) != normal(finding.supporting_quote):
                raise ValueError('Extractive statement differs from its supporting quote')
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f'{finding.finding_id}: {exc}')
    if not findings:
        errors.append('No reviewed findings were available')
    return Verification(passed=not errors, checked_findings=len(findings), errors=errors)
