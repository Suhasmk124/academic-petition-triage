"""Conditional rule positions from explicitly supplied fictional facts; never decisions."""
from typing import Literal
from pydantic import Field, StrictBool
from assessment import Contract, classify


class PetitionFacts(Contract):
    attendance_percent: float | None = Field(default=None,ge=0,le=100,allow_inf_nan=False)
    medical_absence: StrictBool | None = None
    exception_requested: StrictBool | None = None
    summer_term: StrictBool | None = None


def position(petition, facts, result):
    route, reasons, required = 'REFER_TO_COMMITTEE', ['Supporting records and any exceptions require officer review.'], []
    brief = result.get('draft') or result.get('assessment',{})
    citations = {item['citation']['clause_id']:item['evidence_id'] for item in brief.get('claims',brief.get('findings',[]))}
    facts = PetitionFacts.model_validate(facts or {})
    from entities import extract_entities
    stated=extract_entities(petition)['stated_attendance_percent']
    if stated is not None and facts.attendance_percent is not None and stated!=facts.attendance_percent:
        return dict(recommendation='REFER_TO_COMMITTEE',reasons=['The petition and structured attendance figures conflict. An officer must establish the correct record.'],
                    evidence_ids=[],conditional=True,facts_verified=False,human_review_required=True,final_decision_made=False)
    kind = classify(petition)
    if result.get('status')=='REVIEW_REQUIRED':
        if kind=='ATTENDANCE' and facts.attendance_percent is not None:
            required = ['8.1(i)']
            if facts.attendance_percent>=80:
                route = 'GRANT_UNDER_PROVISION'
                reasons = ['If the officer confirms the stated attendance record, the cited 80% threshold appears satisfied. This is a recommendation to process under the provision, not approval.']
            elif facts.medical_absence is False and facts.exception_requested is False:
                route = 'REJECT_UNDER_PROVISION'
                reasons = ['If the officer confirms attendance below 80% and that no applicable condonation or exceptional circumstances apply, the cited examination restriction appears to apply. This is a conditional position, not rejection.']
        elif kind=='X_GRADE' and facts.summer_term is True:
            required = ['5.7(C)(4)']
            route = 'REJECT_UNDER_PROVISION'
            reasons = ['If the officer confirms summer-term registration, the cited provision excludes award of an X grade for that term. This is a conditional position, not a final rejection.']
    if any(clause not in citations for clause in required):
        route, reasons, required = 'REFER_TO_COMMITTEE', ['Required source support is unavailable.'], []
    return dict(recommendation=route,reasons=reasons,evidence_ids=[citations[clause] for clause in required],
                conditional=True,facts_verified=False,human_review_required=True,final_decision_made=False)
