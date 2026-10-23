"""Fixed retrieval regressions; run with python src/test_retrieval.py."""
import json
import sys
from pathlib import Path
from retrieval import (retrieve, fetch_exact_clause, verify_source_quote, resources,
                       read_records, source_pages, validate_record)

CASES = [
    ('attendance', 'What is the minimum attendance percentage and what happens below it?', '8.1', 37, ['80%', 'exceptional circumstances']),
    ('attendance_medical', 'How can attendance shortage be condoned for medical reasons?', '8.1', 37, ['CMO', 'seven', 'recovery']),
    ('medical_deadline', 'What medical certificate and application deadline are required for attendance?', '8.1', 37, ['seven', 'SAP', 'SLCM']),
    ('terminal_medical', 'I missed the terminal examination due to illness. What is the medical leave application deadline?', '5.6', 25, ['seven', 'recovery', 'Chief Medical Officer']),
    ('x_grade', 'What are the X grade retest deadlines and summer term restrictions?', '5.7(C)', 26, ['15 days', 'June 30', 'summer term']),
    ('personal_leave', 'Can personal leave be condoned for attendance purposes?', '8.2', 37, ['will not be']),
    ('makeup_exclusion', 'F grade due to shortage of attendance eligible for summer make-up exam?', '5.7(B)', 26, ['not eligible']),
]


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    report = []
    for name, query, section, page, phrases in CASES:
        result = retrieve(query)
        citations = [c for p in result['passages'] for c in p['citations']]
        matches = [c for c in citations if c['section'] == section and c['pdf_page'] == page]
        text = ' '.join(' '.join(c['exact_quote'].split()) for c in matches)
        passed = bool(matches) and all(phrase.lower() in text.lower() for phrase in phrases)
        assert passed, f'{name}: expected section {section}, page {page}, phrases {phrases}'
        assert all(c['citation_metadata_verified'] and c['printed_page_verified'] for c in matches)
        report.append(dict(case=name, section=section, pdf_page=page, passed=passed,
                           matched_sections=[c['section'] for c in citations]))
        print('PASS:', name)
    exact = json.loads(fetch_exact_clause.invoke({'clause_id': '8.1(iii)'}))
    citation = exact['citations'][0]
    assert 'seven' in citation['exact_quote']
    for quote, expected in [(citation['exact_quote'], True),
                            ('Attendance below 80% is automatically approved.', False), ('', False)]:
        check = json.loads(verify_source_quote.invoke({'evidence_id': citation['evidence_id'], 'quote': quote}))
        assert check['quote_supported'] is expected and not check['claim_entailment_checked']
    unknown = json.loads(verify_source_quote.invoke({'evidence_id': 'invented-id', 'quote': 'seven days'}))
    assert not unknown['quote_supported']
    assert retrieve('zzzxxyyqvv')['status'] == 'NO_SUFFICIENT_EVIDENCE'
    collection, _ = resources()
    record = read_records(collection)[citation['evidence_id']]
    pages = source_pages()
    original = pages[37]
    try:
        pages[37] = original + '\nchanged source'
        try:
            validate_record(record)
        except ValueError:
            pass
        else:
            raise AssertionError('Stale source was accepted')
    finally:
        pages[37] = original
    report.extend([dict(case=name, passed=True) for name in
                   ['exact_quote_checks', 'unknown_evidence_rejected', 'no_overlap_abstains', 'stale_source_rejected']])
    destination = Path(__file__).resolve().parents[1] / 'evaluations/retrieval_smoke_report.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(dict(scope='7 focused retrieval cases plus 4 integrity checks; not the required 20+ scenario evaluation', results=report), indent=2), encoding='utf-8')
    print(f'PASS: {len(report)} checks. Report: {destination}')


if __name__ == '__main__':
    main()
