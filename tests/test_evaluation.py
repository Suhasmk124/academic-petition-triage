"""Evaluation metrics must reject bad quotes, altered citations and unsupported claims."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from evaluate import DATASET, passage_metrics, score_findings


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.citation = {'evidence_id': 'reviewed-1', 'pdf_page': 37, 'exact_quote': 'Apply within seven days of recovery.'}
        self.finding = dict(evidence_id='reviewed-1', citation=self.citation,
                            statement=self.citation['exact_quote'], supporting_quote=self.citation['exact_quote'])

    def test_partial_clause_and_wrong_page_do_not_count_as_complete(self):
        for documents in [[(37, 'Apply within seven days')], [(25, self.citation['exact_quote'])]]:
            self.assertEqual(passage_metrics(documents, [self.citation])['complete_clause_recall'], 0)
        self.assertEqual(passage_metrics([(37, self.citation['exact_quote'])], [self.citation])['complete_clause_recall'], 1)

    def test_page_proxy_counts_irrelevant_returned_units(self):
        score = passage_metrics([(37, self.citation['exact_quote']), (60, 'Other topic')], [self.citation])
        self.assertEqual(score['page_relevance_proxy'], .5)

    def test_altered_citation_quote_claim_or_id_is_unsupported(self):
        canonical = {'reviewed-1': self.citation}
        self.assertEqual(score_findings([self.finding], canonical)['source_grounded'], 1)
        for field, value in [('statement', 'Automatically approved.'), ('supporting_quote', 'Apply whenever you want.'),
                             ('evidence_id', 'invented'), ('citation', {**self.citation, 'pdf_page': 25})]:
            with self.subTest(field=field):
                finding = copy.deepcopy(self.finding)
                finding[field] = value
                self.assertEqual(score_findings([finding], canonical)['unsupported_extractive_findings'], 1)

    def test_empty_output_is_not_perfect_faithfulness(self):
        self.assertIsNone(score_findings([], {})['extractive_faithfulness'])
        self.assertIsNone(passage_metrics([], [])['complete_clause_recall'])

    def test_fixed_dataset_has_unique_cases_and_expected_negative_outcomes(self):
        cases = json.loads(DATASET.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len(cases), len({case['id'] for case in cases}))
        self.assertEqual({case['type'] for case in cases}, {'ATTENDANCE', 'TERMINAL_MEDICAL', 'X_GRADE', 'UNSUPPORTED'})
        self.assertTrue(all(case['status'] == 'ESCALATE' and not case['clauses'] for case in cases if case['type'] == 'UNSUPPORTED'))
