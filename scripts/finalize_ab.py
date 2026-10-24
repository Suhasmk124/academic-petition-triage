"""Preserve quota-limited cells; extract only complete paired A/B observations."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
path=root/'evaluations/prompt_ab_live.json'
raw=json.loads(path.read_text())
if 'raw_quota_run' in raw: raise SystemExit('Already finalized')
(root/'evaluations/prompt_ab_quota_run.json').write_text(json.dumps(raw,indent=2),encoding='utf-8')
grouped={}
for row in raw['results']:
    row['provider_http_succeeded']=any(event.get('success') for event in row['usage'])
    row['orchestration_completed']=row['provider_used']
    if not row['orchestration_completed']:row['source_gate']='MODEL_OUTPUT_UNAVAILABLE'
    grouped.setdefault(row['case'],{})[row['variant']]=row
pairs=[entry for entry in grouped.values() if len(entry)==2 and all(row['provider_http_succeeded'] and not any(event.get('http_status')==429 for event in row['usage']) for row in entry.values())]
results=[row for entry in pairs for row in entry.values()]
report=dict(complete=bool(pairs),paired_cases=len(pairs),variants=2,results=results,
            raw_quota_run='evaluations/prompt_ab_quota_run.json',
            excluded_cases=[case for case,entry in grouped.items() if entry not in pairs],
            tool_start_policy='auto (original orchestration; required initial verifier tool added afterwards)',
            scope='Small paired live experiment. A model/tool failure counts as a failed model output, not a successful deterministic fallback. Rate-limited cells excluded and preserved. Not a held-out statistical benchmark.')
path.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(f'Complete paired cases: {len(pairs)}; excluded quota-limited cases retained in raw report.')
