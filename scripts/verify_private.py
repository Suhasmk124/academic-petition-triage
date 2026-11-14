"""One bounded, non-personal live acceptance run against the private workspace."""
import base64
import json
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1X8AAAAASUVORK5CYII=')
PETITION = 'My attendance is 85%. What attendance provision applies?'


def main():
    url = 'http://127.0.0.1:8002'
    key = (ROOT/'.secrets/private_triage_key').read_text().strip()
    with httpx.Client(base_url=url, headers={'Authorization':'Bearer '+key}, timeout=10) as client:
        deadline = time.monotonic()+120
        while time.monotonic()<deadline:
            try:
                if client.get('/ready').status_code==200: break
            except httpx.TransportError: pass
            time.sleep(2)
        else: raise RuntimeError('Private workspace is not ready')
        health=client.get('/health').json()
        assert health['mode']=='hosted' and health['private_records']
        response=client.post('/petitions/private',json={
            'petition':PETITION,'facts':{'attendance_percent':85},
            'attachment':{'content':base64.b64encode(FIXTURE).decode()}})
        response.raise_for_status()
        poll=response.json()['poll_url']
        try:
            assert httpx.get(url+poll+'/attachment').status_code==401
            assert client.get(poll+'/attachment').content==FIXTURE
            deadline=time.monotonic()+250
            while time.monotonic()<deadline:
                run=client.get(poll).json()
                if run['status'] in ('SUCCEEDED','FAILED'):break
                time.sleep(2)
            else: raise RuntimeError('Private run timed out')
            assert run['attachment_available'] and run['private_petition']==PETITION
            exported=client.get(poll+'/export')
            exported.raise_for_status()
            assert PETITION not in exported.text and base64.b64encode(FIXTURE).decode() not in exported.text
            result=run.get('result') or {}
            report=dict(hosted_verdict_count=len(result.get('hosted_review',[])),run_status=run['status'],output_mode=result.get('mode'),
                        source_gate=result.get('safety',{}).get('output'),
                        hosted_response_used=result.get('provider_response_used',False),
                        hosted_attempts=result.get('provider_request_attempts',0),
                        role_tools=[{'role':m['agent'],'tools':m['tools_used']} for m in result.get('metrics',[])],
                        attachment_download_and_auth_verified=True,export_excluded_private_data=True,
                        final_decision_made=result.get('final_decision_made'))
        finally:
            assert client.delete(poll+'/attachment').status_code==204
            assert client.get(poll+'/attachment').status_code==404
        report['attachment_removed']=True
        (ROOT/'logs/private-live-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
        if not (report['hosted_response_used'] and report['source_gate']=='passed' and report['hosted_verdict_count']==3):
            raise SystemExit(1)


if __name__=='__main__':
    main()
