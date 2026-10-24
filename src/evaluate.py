"""Fixed local evaluation: retrieval comparison and extractive workflow contracts, no hosted calls."""
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'evaluations/scenarios.json'


def passage_metrics(documents, expected):
    """Full expected-clause text coverage + page relevance proxy; never semantic relevance."""
    from retrieval import normal
    covered = sum(any(page == item['pdf_page'] and normal(item['exact_quote']) in normal(text)
                      for page, text in documents) for item in expected)
    pages = {item['pdf_page'] for item in expected}
    return dict(complete_clause_recall=covered / len(expected) if expected else None,
                expected_clauses=len(expected), covered_clauses=covered,
                page_relevance_proxy=sum(page in pages for page, _ in documents) / len(documents) if documents and expected else None,
                returned_units=len(documents), returned_characters=sum(len(text) for _, text in documents))


def score_findings(findings, canonical):
    """All metadata, full quote and extractive statement must match trusted evidence."""
    from retrieval import normal
    checks = []
    for finding in findings:
        item = canonical.get(finding.get('evidence_id'))
        checks.append(bool(item and finding.get('citation') == item
                           and normal(finding.get('supporting_quote', '')) == normal(item['exact_quote'])
                           and normal(finding.get('statement', '')) == normal(item['exact_quote'])))
    return dict(findings=len(checks), source_grounded=sum(checks),
                extractive_faithfulness=sum(checks) / len(checks) if checks else None,
                unsupported_extractive_findings=sum(not check for check in checks))


def main():
    import chromadb
    from hosted_model import HostedChat
    from retrieval import resources, read_records, citation, validate_record, retrieve
    from workflow import run_petition
    from stub_model import run_stub
    from safety import guarded_result
    raw = DATASET.read_bytes()
    cases = json.loads(raw)
    if len(cases) < 20 or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('At least 20 uniquely identified fixed scenarios are required')
    collection, embedding = resources()
    records = read_records(collection)
    canonical = {}
    for record in records.values():
        if record['metadata']['citation_metadata_verified']:
            validate_record(record)
            canonical[record['id']] = citation(record)
    by_clause = {item['clause_id']: item for item in canonical.values()}
    legacy = chromadb.PersistentClient(path=str(ROOT / 'data/chroma_db')).get_collection('iisc_academic_regulations')
    rows = []
    # Fail closed if evaluation ever accidentally reaches the hosted adapter.
    with patch.object(HostedChat, 'complete', side_effect=AssertionError('Hosted requests are forbidden during local evaluation')):
        for case in cases:
            expected = [by_clause[clause] for clause in case['clauses']]
            if set(case['pages']) != {item['pdf_page'] for item in expected}:
                raise ValueError(f"Expected page labels do not match reviewed clauses: {case['id']}")
            retrieval = {}
            if expected:
                old = legacy.query(query_embeddings=[embedding.embed_query(case['petition'])], n_results=8,
                                   include=['documents', 'metadatas', 'distances'])
                old_documents = [(m['page'] if 'page' in m else m['pdf_page'], text)
                                 for m, text, distance in zip(old['metadatas'][0], old['documents'][0], old['distances'][0]) if distance <= 1.15]
                new = retrieve(case['petition'])
                new_documents = [(c['pdf_page'], c['exact_quote']) for passage in new['passages'] for c in passage['citations']]
                retrieval = dict(baseline=passage_metrics(old_documents, expected), current=passage_metrics(new_documents, expected))
            workflows = {}
            for name, runner in [('deterministic', run_petition), ('stub', lambda text: run_stub(text, delay=0))]:
                result = runner(case['petition'])
                service_output = guarded_result(result, case['petition'])
                brief = result.get('draft') or result['assessment']
                findings = brief.get('claims', brief.get('findings', []))
                score = score_findings(findings, canonical)
                clauses = {finding['citation']['clause_id'] for finding in findings}
                passed = (result['status'] == case['status'] and clauses == set(case['clauses'])
                          and score['unsupported_extractive_findings'] == 0
                          and brief['routing_recommendation'] == 'REFER_TO_COMMITTEE'
                          and (result.get('final_decision_made', brief.get('final_decision_made')) is False)
                          and (result.get('human_review_required', brief.get('human_review_required')) is True))
                if name == 'deterministic':
                    passed = passed and brief['petition_type'] == case['type']
                else:
                    passed = passed and result['billable_model_requests'] == 0 and not result['provider_response_used']
                    if expected:
                        passed = passed and result['stub_workflow_path'] == 'TWO_ROLE_SIMULATED'
                guard_passed = service_output['safety']['output'] == 'passed' and service_output['status'] == case['status']
                passed = passed and guard_passed
                workflows[name] = dict(passed=passed, status=result['status'], service_output_guard_passed=guard_passed, **score)
            rows.append(dict(id=case['id'], retrieval=retrieval, workflows=workflows))
            print('PASS:' if all(item['passed'] for item in workflows.values()) else 'FAIL:', case['id'], flush=True)
    comparisons = [row['retrieval'] for row in rows if row['retrieval']]
    summary = {}
    for name in ('baseline', 'current'):
        summary[name] = {metric: round(sum(row[name][metric] for row in comparisons) / len(comparisons), 4)
                         for metric in ('complete_clause_recall', 'page_relevance_proxy', 'returned_units', 'returned_characters')}
    passed = all(item['passed'] for row in rows for item in row['workflows'].values())
    report = dict(dataset_version=1, dataset_sha256=hashlib.sha256(raw).hexdigest(), scenarios=len(cases),
                  supported_retrieval_cases=len(comparisons), workflow_runs=len(cases) * 2, all_workflows_passed=passed,
                  billable_model_requests=0, retrieval_comparison=summary,
                  scope='Fixed pilot scenarios; full-clause recall, page relevance proxy and exact extractive source faithfulness. No semantic quality or eligibility score.',
                  comparison_policy='Historical vector k=8, distance<=1.15 versus current hybrid<=4 section groups. Different context budgets; unit and character counts reported. This is a pipeline comparison, not an isolated ranker or prompt A/B experiment.',
                  limitations=['Keyword classification remains narrow; these cases do not establish broad out-of-corpus detection.',
                               'The dataset was authored after the pilot implementation; it is a regression set, not a held-out benchmark.',
                               'Page overlap is only a relevance proxy; exact quotes do not prove semantic entailment.',
                               'Hosted semantic evaluation, prompt A/B, injection and toxicity evaluations remain planned.'],
                  results=rows)
    (ROOT / 'evaluations/fixed_suite_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not passed:
        raise AssertionError('Fixed workflow evaluation failed; inspect fixed_suite_report.json')
    print(f'PASS: {len(cases)} fixed scenarios, {len(cases) * 2} local workflow runs; zero hosted model requests.')
    return report


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
