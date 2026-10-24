"""Isolated local execution. Parent owns the deadline and kills overdue subprocesses."""
import json
import sys
from pathlib import Path


def main():
    payload = json.loads(sys.stdin.read())
    import torch
    torch.set_num_threads(1)
    from telemetry import span
    with span('isolated.workflow',parent=payload.get('traceparent')):
        result = execute(payload)
    result.pop('evidence',None)
    Path(payload['output']).write_text(json.dumps(result),encoding='utf-8')


def execute(payload):
    mode, petition = payload['mode'], payload['petition']
    if mode == 'stub':
        from stub_model import run_stub
        result = run_stub(petition, payload.get('delay', .15))
    elif mode == 'hosted':
        from agent_workflow import run_hosted
        result = run_hosted(petition)
    else:
        from workflow import run_petition
        result = run_petition(petition) | {'mode':'DETERMINISTIC','billable_model_requests':0}
    return result


if __name__ == '__main__':
    main()
