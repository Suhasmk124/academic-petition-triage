import json
from pathlib import Path
queries = [
    ('HTTP p95','histogram_quantile(0.95, sum by (le) (rate(triage_http_duration_seconds_bucket[5m])))'),
    ('Queue depth','triage_jobs{status="QUEUED"}'),
    ('Active workers','triage_active_workers'),
    ('Agent calls','triage_agent_runs_total'),
    ('Agent time','triage_agent_duration_seconds_sum'),
    ('Tool calls','triage_agent_tool_calls_total'),
    ('Model retries','triage_agent_retries_total'),
    ('API uptime','triage_uptime_seconds'),
    ('Tokens (reported or estimated)','triage_tokens_total')]
panels = [dict(id=i+1,title=title,type='timeseries',datasource=dict(type='prometheus',uid='prometheus'),
               gridPos=dict(x=(i%2)*12,y=(i//2)*8,w=12,h=8),targets=[dict(expr=query,refId='A')]) for i,(title,query) in enumerate(queries)]
destination = Path(__file__).resolve().parents[1]/'deploy/grafana/dashboards/triage.json'
destination.parent.mkdir(parents=True,exist_ok=True)
destination.write_text(json.dumps(dict(title='Academic petition operations',uid='petition-triage',schemaVersion=39,
                                      version=1,refresh='5s',time={'from':'now-15m','to':'now'},panels=panels),indent=2),encoding='utf-8')
