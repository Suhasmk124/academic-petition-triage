"""Deterministic LangGraph evidence handoff; LLM roles live in agent_workflow.py."""
import argparse
import json
import sys
from typing import Literal, TypedDict
from langgraph.graph import END, START, StateGraph
from assessment import Assessment, PetitionRequest, Verification, build_assessment, verify_findings
from retrieval import read_records, resources, search_regulations, validate_record

MAX_SEARCHES = 2

class PetitionState(TypedDict, total=False):
    petition: str
    evidence: dict
    assessment: dict
    verification: dict
    searches: int
    status: str

def investigate(state):
    query = state['petition']
    if state.get('searches', 0):
        query = ' '.join(state.get('assessment', {}).get('missing_provisions', [])) + ' ' + query
    try:
        evidence = json.loads(search_regulations.invoke({'query': query}))
        if not isinstance(evidence, dict):
            raise ValueError('Retrieval must return an object')
        assessment = build_assessment(state['petition'], evidence)
    except Exception as exc:
        evidence = {'status': 'NO_SUFFICIENT_EVIDENCE', 'passages': [],
                    'reason': f'Retrieval failure: {type(exc).__name__}'}
        assessment = build_assessment(state['petition'], evidence)
    return {'evidence': evidence, 'assessment': assessment.model_dump(),
            'searches': state.get('searches', 0) + 1}

def verify(state):
    assessment = Assessment.model_validate(state['assessment'])
    if assessment.petition_type == 'UNSUPPORTED':
        check = Verification(passed=False, errors=['This petition type is outside the reviewed pilot scope.'])
    else:
        try:
            collection, _ = resources()
            check = verify_findings(assessment.findings, read_records(collection), validate_record)
        except Exception as exc:
            check = Verification(passed=False, errors=[f'Source verification unavailable: {type(exc).__name__}'])
    if assessment.missing_provisions:
        check.passed = False
        check.errors.append('Missing provisions: ' + ', '.join(assessment.missing_provisions))
    if check.passed:
        status = 'REVIEW_REQUIRED'
        assessment.reasons.append('Every extractive finding matches its canonical quotation and citation metadata.')
    elif state['searches'] < MAX_SEARCHES and assessment.petition_type != 'UNSUPPORTED':
        status = 'RETRY'
    else:
        status = 'ESCALATE'
        assessment.findings = []
        assessment.reasons.append('Evidence could not be verified; no eligibility position is supported.')
    assessment.routing_recommendation = 'REFER_TO_COMMITTEE'
    return {'assessment': assessment.model_dump(), 'verification': check.model_dump(), 'status': status}

def route_after_verification(state) -> Literal['investigate', 'finish']:
    return 'investigate' if state['status'] == 'RETRY' and state['searches'] < MAX_SEARCHES else 'finish'

builder = StateGraph(PetitionState)
builder.add_node('investigate', investigate)
builder.add_node('verify', verify)
builder.add_edge(START, 'investigate')
builder.add_edge('investigate', 'verify')
builder.add_conditional_edges('verify', route_after_verification, {'investigate': 'investigate', 'finish': END})
app = builder.compile()

def run_petition(petition):
    # Invalid input never reaches the graph through this entry point; API validation runs before queueing.
    request = PetitionRequest(petition=petition)
    from safety import check_input
    check_input(request.petition)
    return app.invoke({'petition': request.petition, 'searches': 0, 'status': 'STARTED'},
                      config={'recursion_limit': 10})

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--petition', default='My attendance is 72%. I missed classes because of a medical issue. What are the medical condonation requirements?')
    result = run_petition(parser.parse_args().petition)
    print(json.dumps({key: value for key, value in result.items() if key != 'evidence'},
                     ensure_ascii=False, indent=2))
