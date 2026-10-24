"""Bounded final hosted-role smoke with complete canonical extractive source checks."""
import json
import argparse
from pathlib import Path
from agent_workflow import run_agents,ROOT
from hosted_model import HostedChat,HostedSettings,ModelUnavailable
from safety import guarded_result


class BudgetChat(HostedChat):
    max_requests=8
    def complete(self,*arguments,**keywords):
        if len(self.events)>=self.max_requests-1: raise ModelUnavailable('Final acceptance request budget reached')
        result=super().complete(*arguments,**keywords)
        # Record structure only, never raw provider text or petition contents.
        summary=dict(content_characters=len(result.get('content') or ''),tools=[])
        for call in result.get('tool_calls',[]):
            function=call.get('function',{})
            try:
                payload=json.loads(function.get('arguments','{}'))
                keys=list(payload) if isinstance(payload,dict) else []
            except ValueError: keys=['INVALID_JSON']
            summary['tools'].append(dict(name=function.get('name'),argument_keys=keys))
        self.events[-1]['response_shape']=summary
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-requests',type=int,default=8)
    args=parser.parse_args()
    if not 2<=args.max_requests<=12:parser.error('Request budget must be between 2 and 12')
    petition='Synthetic public-handbook question: what are the attendance threshold, CMO certification requirements, and SLCM medical leave deadline?'
    model=BudgetChat(HostedSettings.from_env())
    model.max_requests=args.max_requests
    try:
        result=run_agents(petition,model,variant='strict')
        output=guarded_result(result,petition)
        passed=(result.get('mode')=='HOSTED_AGENTS' and result['status']=='REVIEW_REQUIRED'
                and output['safety']['output']=='passed' and len(result.get('draft',{}).get('claims',[]))==3)
        report=dict(passed=passed,provider_completed_two_roles=result.get('mode')=='HOSTED_AGENTS',
                    source_gate=output['safety']['output'],status=result['status'],
                    claims=len(result.get('draft',{}).get('claims',[])),metrics=result.get('metrics',[]),
                    usage=[{key:event.get(key) for key in ('agent','attempt','http_status','success','input_tokens','output_tokens','billed_cost_usd','latency_seconds','provider_error_code','provider_error_type','provider_error_message','response_shape')} for event in model.events],
                    failure_type=result.get('hosted_failure'),failure_reason=result.get('hosted_failure_reason'),
                    scope='One live synthetic acceptance case. Full extractive identity, canonical metadata, complete pilot provision coverage and human-review boundary checked. This is not proof of broad LLM semantic accuracy.')
        (ROOT/'evaluations/hosted_postguard_smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'passed':passed,'provider_completed':report['provider_completed_two_roles'],'http_attempts':len(model.events)}))
        if not passed: raise SystemExit(1)
    finally:model.close()


if __name__=='__main__':main()
