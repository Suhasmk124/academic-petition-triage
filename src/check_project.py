"""One combined regression run after implementation changes."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
    unit = unittest.TextTestRunner(verbosity=1).run(suite)
    if not unit.wasSuccessful():
        raise SystemExit(1)
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
    report = dict(unit_tests=unit.testsRun, unit_passed=True, retrieval_checks=11,
                  live_workflows=results, hosted_orchestration_implemented=True, live_hosted_validation=False,
                  semantic_entailment_verified=False,
                  scope='Focused regressions; not the required full 20+ scenario quality evaluation.')
    (ROOT / 'evaluations/project_checks.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'PASS: {unit.testsRun} unit tests, 11 retrieval checks, {len(results)} real workflow cases.')

if __name__ == '__main__':
    main()
