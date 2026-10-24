"""Fixed local rule checks. No model-based security or semantic assessment."""
import json
from pathlib import Path
from safety import VERSION, content_flags

ROOT = Path(__file__).resolve().parents[1]


def main():
    cases = json.loads((ROOT / 'evaluations/safety_scenarios.json').read_text(encoding='utf-8'))
    rows = [dict(id=case['id'], expected_blocked=case['blocked'], flags=content_flags(case['text']),
                 passed=bool(content_flags(case['text'])) == case['blocked']) for case in cases]
    report = dict(version=VERSION, cases=len(rows), all_passed=all(row['passed'] for row in rows),
                  billable_model_requests=0, results=rows,
                  scope='Small post-implementation rule regression set, not a security benchmark. English patterns, NFKC and format-character normalization only. Encoded, paraphrased, multilingual and novel attacks can bypass these rules; benign quoted instructions/insults may be blocked.')
    (ROOT / 'evaluations/safety_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not report['all_passed']:
        raise AssertionError('Safety rule regressions failed')
    print(f"PASS: {len(rows)} safety rule scenarios; no hosted calls.")
    return report


if __name__ == '__main__':
    main()
