"""Regression checks for evidence handoff and failure routing; no model needed."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pydantic import ValidationError
import workflow
from assessment import Assessment, build_assessment, verify_findings
from index_corpus import reviewed
from retrieval import citation, source_pages, validate_record

class AssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = {r['id']: {'id': r['id'], 'text': r['text'], 'metadata': r['metadata']}
                       for r in reviewed(source_pages())}
        cls.evidence = {'status': 'CANDIDATES_RETRIEVED', 'passages': [
            {'citations': [citation(r) for r in cls.records.values()]}]}

    def run_graph(self, petition, evidence=None, sequence=None):
        with patch('workflow.search_regulations') as search, patch('workflow.resources', return_value=(None, None)), patch('workflow.read_records', return_value=self.records):
            search.invoke.side_effect = sequence
            search.invoke.return_value = json.dumps(self.evidence if evidence is None else evidence)
            result = workflow.run_petition(petition)
            self.assertLessEqual(search.invoke.call_count, 2)
            return result

    def test_attendance_findings_and_human_route(self):
        result = self.run_graph('My attendance is 72% after illness.')
        assessment = result['assessment']
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertEqual(len(assessment['findings']), 3)
        self.assertEqual(result['verification']['checked_findings'], 3)
        self.assertFalse(result['verification']['semantic_entailment_checked'])
        self.assertEqual(assessment['routing_recommendation'], 'REFER_TO_COMMITTEE')
        self.assertTrue(assessment['human_review_required'])
        self.assertFalse(assessment['final_decision_made'])
        self.assertTrue(assessment['missing_evidence'])

    def test_terminal_absence_uses_exam_provisions(self):
        result = self.run_graph('I missed the terminal examination due to illness.')
        self.assertEqual(result['assessment']['petition_type'], 'TERMINAL_MEDICAL')
        self.assertEqual(result['verification']['checked_findings'], 6)
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')

    def test_x_grade(self):
        result = self.run_graph('What are the X grade retest deadlines?')
        self.assertEqual(result['verification']['checked_findings'], 5)

    def test_unknown_type_escalates_even_with_attendance_evidence(self):
        result = self.run_graph('Please refund my parking ticket.')
        self.assertEqual(result['status'], 'ESCALATE')
        self.assertEqual(result['searches'], 1)
        self.assertEqual(result['assessment']['findings'], [])

    def test_missing_provisions_retry_then_escalate(self):
        result = self.run_graph('Attendance medical condonation', evidence={'passages': []})
        self.assertEqual(result['status'], 'ESCALATE')
        self.assertEqual(result['searches'], 2)
        self.assertEqual(result['assessment']['findings'], [])

    def test_research_recovers(self):
        result = self.run_graph('Attendance medical condonation', sequence=[json.dumps({'passages': []}), json.dumps(self.evidence)])
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertEqual(result['searches'], 2)

    def test_malformed_retrieval_escalates(self):
        result = self.run_graph('Attendance', sequence=['bad json', 'bad json'])
        self.assertEqual(result['status'], 'ESCALATE')
        self.assertEqual(result['searches'], 2)

    def test_invalid_request_does_not_invoke_graph(self):
        for petition in (' ', 'x' * 4001):
            with patch.object(workflow.app, 'invoke') as graph:
                with self.assertRaises(ValidationError):
                    workflow.run_petition(petition)
                graph.assert_not_called()

    def test_altered_statement_is_rejected(self):
        assessment = build_assessment('Attendance', self.evidence)
        assessment.findings[0].statement = 'Automatically approve attendance below 80%.'
        self.assertFalse(verify_findings(assessment.findings, self.records, validate_record).passed)

    def test_wrong_citation_page_is_rejected(self):
        assessment = build_assessment('Attendance', self.evidence)
        assessment.findings[0].citation['pdf_page'] = 25
        self.assertFalse(verify_findings(assessment.findings, self.records, validate_record).passed)

    def test_invented_evidence_is_rejected(self):
        assessment = build_assessment('Attendance', self.evidence)
        assessment.findings[0].evidence_id = 'invented'
        self.assertFalse(verify_findings(assessment.findings, self.records, validate_record).passed)

    def test_stale_source_is_rejected(self):
        assessment = build_assessment('Attendance', self.evidence)
        changed = copy.deepcopy(self.records)
        changed[assessment.findings[0].evidence_id]['metadata']['page_text_sha256'] = 'stale'
        self.assertFalse(verify_findings(assessment.findings, changed, validate_record).passed)

    def test_failed_graph_verification_discards_findings(self):
        evidence = copy.deepcopy(self.evidence)
        next(c for c in evidence['passages'][0]['citations'] if c['clause_id'] == '5.6(i)')['pdf_page'] = 99
        result = self.run_graph('Medical absence from terminal examination', evidence=evidence)
        self.assertEqual(result['status'], 'ESCALATE')
        self.assertEqual(result['assessment']['findings'], [])

    def test_final_decision_is_forbidden_by_contract(self):
        with self.assertRaises(ValidationError):
            Assessment(petition_type='ATTENDANCE', final_decision_made=True)

if __name__ == '__main__':
    unittest.main()
