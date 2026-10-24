# Service runbook

Use synthetic petitions only. Commands run from the project root. Compose binds host ports to loopback and enables a shared workspace key. The optional standalone API has authentication only when a key is configured. Do not use hosted calls to diagnose routine queue or source issues. Container setup is documented in [operations.md](operations.md).

## Worker unavailable: jobs remain queued

Check connectivity and worker readiness:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

A ready check returns HTTP 503 when no worker has heartbeated recently or configured Redis is unavailable. In Compose, inspect `docker compose ps` and `docker compose logs --tail 50 worker redis`; restore replicas with `docker compose up -d --scale worker=3`. For standalone development, start the existing worker in another terminal:

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

## Simulated model service unavailable or circuit open

Inspect `docker compose ps stub` and `docker compose logs --tail 50 stub worker`. The worker makes at most two HTTP attempts, backs off, and opens its process-local circuit after three failed calls for 30 seconds. It uses the isolated deterministic source-backed fallback; the result's `reliability` field records the reason. It does not call a paid or alternate model. A cache hit can hide an outage; the controlled failure driver disables cache and uses one worker to observe the same circuit instance.

Restore with `docker compose start stub`, wait for its warmed health check, then allow the circuit recovery interval. A new fictional run should have `reliability.fallback=false` and a valid source gate. Existing completed fallback runs retain their audit evidence. If both remote work and fallback exceed the total job deadline, the run fails with sanitized `WORKFLOW_TIMEOUT`; investigate logs by run/correlation ID. Do not extend deadlines to mask a hung dependency.

## Free-provider quota or output-contract failure

Routine Compose use needs no hosted credentials. For an explicit live test, inspect the sanitized acceptance report. HTTP 429 stops without retry or paid fallback; wait for the provider's reset before another deliberate test. An HTTP 200 response can still fail the schema/source gate and does not count as successful role completion. Schema feedback stays within the original six-turn limit. Preserve the failure report, reproduce with a scripted regression, then use one bounded live check. Recovery requires both real roles and the canonical source gate to pass, not simply a successful HTTP status.

## Authentication/rate limit

Read the local key from `.secrets/triage_key` into the portal without sharing it in chat, screenshots or Git. A teammate generates their own deployment keys. A 401 indicates an absent/expired session or wrong key; sign in again. A 429 from submission indicates the fixed-window limit; wait for the next minute. Do not disable rate limits to bypass routine rejection. The benchmark/failure scripts temporarily use explicit measurement settings and restore normal settings afterwards.
