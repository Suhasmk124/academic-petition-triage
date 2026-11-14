import copy
import unittest
from hosted_model import ModelUnavailable
from hosted_diagnostics import hosted_failure_details
from safety import guarded_result
import test_hosted_agents as fixtures
from test_safety_feedback import good_result


class HostedResultTests(unittest.TestCase):
    def test_canonical_verdicts_survive_gate_and_do_not_expose_untrusted_reason(self):
        source = good_result()
        claims = [{k:v for k,v in item.items() if k not in ('finding_id','kind')} | {'claim_id':item['finding_id']}
                  for item in source['assessment']['findings']]
        raw = dict(status='REVIEW_REQUIRED', mode='HOSTED_AGENTS', provider_response_used=True,
                   human_review_required=True, final_decision_made=False,
                   draft=dict(claims=claims,routing_recommendation='REFER_TO_COMMITTEE'),
                   review=dict(needs_research=False,verdicts=[
                       dict(claim_id=c['claim_id'],supported=True,reason='UNTRUSTED-RAW-TEXT') for c in claims]))
        output = guarded_result(raw,'attendance')
        self.assertEqual(output['safety']['output'],'passed')
        self.assertEqual([x['clause_id'] for x in output['hosted_review']],
                         [c['citation']['clause_id'] for c in claims])
        self.assertNotIn('UNTRUSTED-RAW-TEXT',str(output))
        for index in (0,1):
            bad=copy.deepcopy(raw)
            if index:
                bad['review']['verdicts'][0]['supported']=False
            else:
                bad['review']['verdicts'].pop()
            rejected=guarded_result(bad,'attendance')
            self.assertEqual(rejected['safety']['output'],'blocked')
            self.assertNotIn('hosted_review',rejected)

    def test_verifier_repairs_provider_format_without_tools_after_quote_check(self):
        class RecoveringModel(fixtures.ScriptedModel):
            def complete(self, role, messages, tools):
                if role=='verifier' and len([call for call in self.calls if call[0]=='verifier'])==1:
                    self.calls.append((role,messages,tools))
                    raise ModelUnavailable('provider rejected format','TOOL_FORMAT_REJECTED')
                return super().complete(role,messages,tools)
        model=RecoveringModel(verifier=[fixtures.verify_call(),fixtures.final(fixtures.REVIEW)])
        result=fixtures.AgentTests().run_model(model)
        self.assertEqual(result['mode'],'HOSTED_AGENTS')
        self.assertEqual(model.calls[-1][2],[])
        self.assertTrue(result['metrics'][-1]['success'])

    def test_failure_detail_only_exposes_fixed_message_and_safe_metadata(self):
        detail=hosted_failure_details({'hosted_failure_code':'RATE_LIMITED','metrics':[{'agent':'verifier'}],
            'model_usage':[{'http_status':429,'provider_error_message':'SECRET'}],'hosted_failure_reason':'SECRET'})
        self.assertEqual(detail['http_status'],429)
        self.assertEqual(detail['role'],'verifier')
        self.assertNotIn('SECRET',str(detail))
