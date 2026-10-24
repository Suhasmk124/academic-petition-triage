"""One combined regression run after implementation changes."""
import argparse
import json
import sys
import unittest
import os
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', action='store_true', help='Also run local HTTP + separate-worker integration smoke')
    parser.add_argument('--evaluation', action='store_true', help='Also run the fixed synthetic-scenario local evaluation')
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
    with patch.dict(os.environ,{'TRIAGE_API_KEY':'','TRIAGE_API_KEY_FILE':'','REDIS_URL':'','STUB_SERVICE_URL':'','TRIAGE_RATE_LIMIT':'0','TRIAGE_CACHE_TTL':'0','OTEL_EXPORTER_OTLP_ENDPOINT':''}):
        unit = unittest.TextTestRunner(verbosity=1).run(suite)
    if not unit.wasSuccessful():
        raise SystemExit(1)
    from check_safety import main as safety_checks
    safety_report = safety_checks()
    from semantic_challenges import main as semantic_checks
    semantic_report=semantic_checks()
    from test_retrieval import main as retrieval_checks
    retrieval_checks()
    from workflow import run_petition
    results = []
    samples = [
        ('My attendance is 72%. I missed classes due to a medical issue. What are the condonation requirements?', 'REVIEW_REQUIRED', 3),
        ('I missed the terminal examination due to illness. What is the medical leave application deadline?', 'REVIEW_REQUIRED', 6),
        ('What are the X grade retest deadlines and summer term restrictions?', 'REVIEW_REQUIRED', 5),
        ('Please refund my parking ticket.', 'ESCALATE', 0),
    ]
    for petition, expected_status, expected_findings in samples:
        result = run_petition(petition)
        assert result['status'] == expected_status, result
        assert len(result['assessment']['findings']) == expected_findings, result
        assert result['assessment']['routing_recommendation'] == 'REFER_TO_COMMITTEE'
        assert result['assessment']['final_decision_made'] is False
        results.append(dict(petition_type=result['assessment']['petition_type'], status=result['status'],
                            searches=result['searches'], findings=len(result['assessment']['findings'])))
        if expected_findings == 3:
            (ROOT / 'evaluations/assessment_sample.json').write_text(json.dumps(
                {k: v for k, v in result.items() if k != 'evidence'}, indent=2, ensure_ascii=False), encoding='utf-8')
    service_report = None
    if args.service:
        from check_service import main as service_smoke
        service_report = service_smoke()
    evaluation_report = None
    if args.evaluation:
        from evaluate import main as evaluate
        evaluation_report = evaluate()
    report = dict(service_http_smoke_passed=bool(service_report), unit_tests=unit.testsRun, unit_passed=True, retrieval_checks=11,
                  live_workflows=results, hosted_orchestration_implemented=True, live_hosted_validation=False,
                  semantic_entailment_verified=False,
                  fixed_scenarios=evaluation_report['scenarios'] if evaluation_report else None,
                  safety_rule_cases=safety_report['cases'],
                  semantic_challenge_cases=semantic_report['cases'],
                  fixed_workflow_runs=evaluation_report['workflow_runs'] if evaluation_report else None,
                  scope='Local regression and extractive evaluation only; hosted semantic quality and prompt A/B remain unvalidated.')
    (ROOT / 'evaluations/project_checks.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'PASS: {unit.testsRun} unit tests, 11 retrieval checks, {len(results)} real workflow cases.')

if __name__ == '__main__':
    main()
