"""Real free-provider A/B smoke, bounded and resumable. No paid/provider fallback."""
import argparse
import hashlib
import json
from pathlib import Path
from agent_workflow import run_agents, ROOT, PROMPT_VARIANTS
from hosted_model import HostedChat, HostedSettings, ModelUnavailable
from safety import guarded_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--cases',type=int,default=2,choices=range(1,5))
    parser.add_argument('--max-requests',type=int,default=24)
    args = parser.parse_args()
    target = ROOT/'evaluations/prompt_ab_live.json'
    scenarios = json.loads((ROOT/'evaluations/scenarios.json').read_text(encoding='utf-8'))[:args.cases]
    reports = []
    class BudgetChat(HostedChat):
        def complete(self,*pos,**kw):
            if len(self.events)>=args.max_requests: raise ModelUnavailable('Evaluation request budget reached')
            return super().complete(*pos,**kw)
    model = BudgetChat(HostedSettings.from_env())
    try:
        for case in scenarios:
            for variant in ('baseline','strict'):
                before = len(model.events)
                result = run_agents(case['petition'],model,variant=variant)
                guarded = guarded_result(result,case['petition'])
                completed = result.get('mode')=='HOSTED_AGENTS'
                row = dict(case=case['id'],variant=variant,provider_used=any(event.get('success') for event in model.events[before:]),
                           orchestration_completed=completed, failure_type=result.get('hosted_failure'),
                           orchestration_status=result['status'],source_gate=guarded['safety']['output'] if completed else 'MODEL_OUTPUT_UNAVAILABLE',
                           accepted_findings=len((guarded.get('draft') or guarded.get('assessment',{})).get('claims',[])),
                           prompts={role:hashlib.sha256((ROOT/'prompts'/f'{role}_{version}.txt').read_bytes()).hexdigest()
                                    for role,version in PROMPT_VARIANTS[variant].items()},
                           usage=[{key:event.get(key) for key in ('agent','attempt','http_status','success','input_tokens','output_tokens','billed_cost_usd','latency_seconds')} for event in model.events[before:]])
                reports.append(row)
                target.write_text(json.dumps(dict(results=reports,complete=False),indent=2),encoding='utf-8')
                print(f"{variant} {case['id']}: provider={row['provider_used']}, source_gate={row['source_gate']}",flush=True)
                if any(event.get('http_status')==429 for event in model.events[before:]):
                    raise ModelUnavailable('Free quota exhausted; partial report retained')
        complete = all(row['provider_used'] for row in reports) and len(reports)==args.cases*2
        report = dict(complete=complete,cases=args.cases,variants=2,hosted_http_attempts=len(model.events),
                      results=reports,scope='Live paired prompt smoke on fixed synthetic questions; not a held-out statistical benchmark. Exact full-quote fidelity and canonical source gates are measured. LLM entailment judgments remain fallible.')
        target.write_text(json.dumps(report,indent=2),encoding='utf-8')
        if not complete: raise SystemExit('A/B incomplete: provider unavailable for one or more cases.')
    finally:
        model.close()


if __name__=='__main__': main()
