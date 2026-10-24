# Local service runbook

Use synthetic petitions only. Commands run from `C:\Sauce\academic-petition-triage`. The service remains bound to loopback without authentication. Do not use hosted calls to diagnose routine queue or source issues.

## Worker unavailable: jobs remain queued

Check connectivity and worker readiness:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

A ready check returns HTTP 503 when no worker has heartbeated recently. Start the existing worker in another terminal:

```powershell
$env:TRIAGE_MODE = 'stub'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe src\worker.py
```

Use the same `TRIAGE_DB_PATH` for both processes. Reopen the existing run in the portal; do not repeatedly resubmit it. A cold model load can take longer than subsequent requests. Readiness measures heartbeat availability, not model warmup. Abandoned jobs are reclaimed after lease expiry, with at most two attempts; exhausted leases become failed jobs. Check the run status and sanitized error code, using run/correlation IDs in local logs. Do not delete the runtime database to fix a queue problem. Recovery is confirmed when `/ready` returns 200 and the existing run reaches `SUCCEEDED` or a visible `FAILED` state. A triage escalation remains a valid processing outcome.

## Content rejected or final source gate withholds output

For a 403 `CONTENT_REQUIRES_REVIEW`, use the returned rule codes and quarantine ID to understand the input check. The request did not enter the queue. Remove embedded system commands or abusive wording while retaining the fictional academic question. Benign quotations can trigger the limited rules; retain that case for manual assessment rather than disabling safeguards.

For a completed run with `safety.output=blocked`, the proposed result was withheld and no findings should appear. Open `/quality-samples` and find the run ID; compare the canonical source and retrieval smoke report. Check source/index consistency without deleting collections:

```powershell
.\.venv\Scripts\python.exe src\index_corpus.py --preview
.\.venv\Scripts\python.exe src\test_retrieval.py
```

If preview identifies a genuine stale index, apply the existing incremental update:

```powershell
.\.venv\Scripts\python.exe src\index_corpus.py --apply
```

Re-run the combined project checks before accepting a fix. Keep the escalated run for audit and submit a new fictional case after the fix; completed results are not silently rewritten. If the problem is semantic rather than stale source metadata, source integrity checks alone will not resolve it. Refer to a human officer and record the defect. Recovery requires correct canonical citations, no final-decision flag, and a passing regression covering the observed defect.
