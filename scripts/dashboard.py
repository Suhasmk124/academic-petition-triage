import json
from pathlib import Path
queries = [
    ('Workflow p95 (seconds)','histogram_quantile(0.95, sum by (le) (rate(triage_workflow_duration_seconds_bucket{status="SUCCEEDED"}[1m])))'),
    ('Workflows completed per second','sum by (status) (rate(triage_workflow_duration_seconds_count[1m]))'),
    ('Queue depth','triage_jobs{status="QUEUED"}'),
    ('Active workers','triage_active_workers'),
    ('Oldest queued petition (seconds)','triage_oldest_queued_seconds'),
    ('Failed workflows in the last minute','increase(triage_workflow_duration_seconds_count{status="FAILED"}[1m])'),
    ('Submission HTTP p95 (seconds)','histogram_quantile(0.95, sum by (le) (rate(triage_http_duration_seconds_bucket{route=~"/petitions(/private)?"}[1m])))'),
    ('API errors per second','sum by (status) (rate(triage_http_requests_total{status=~"[45].."}[1m]))'),
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
