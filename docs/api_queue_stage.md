# Asynchronous API and queue stage

## Implemented

FastAPI accepts a validated synthetic petition, commits it to a persistent SQLite queue and returns HTTP 202 plus a run ID. The HTTP request does not run the workflow or load the embedding model. A separate worker claims queued jobs and saves their results. Polling distinguishes job execution state from the academic triage recommendation.

- POST /petitions — JSON object with petition (1–4000 nonblank characters) and synthetic: true. Extra fields, including client-selected model/mode fields, are rejected.
- GET /runs/{run_id} — QUEUED, RUNNING, SUCCEEDED or FAILED; includes a result only after completion. triage_status is separate (for example REVIEW_REQUIRED or ESCALATE).
- GET /health — database status, configured mode, queue counts and recent worker count.
- GET /ready — HTTP 503 until a recent worker heartbeat exists. It does not assert embedding/model warm-up or corpus readiness.
- GET /docs — generated interactive API documentation.

The default stub mode uses a scripted model with the existing LangGraph two-role path and real local retrieval/source checks. It explicitly reports simulated: true and zero billable model requests. Unsupported pilot types use the deterministic escalation path. The model does not judge semantic entailment in stub mode. Deterministic mode is also supported. Hosted mode is deliberately not enabled through this API, regardless of a Groq key in .env.

Malformed JSON, wrong content type, schema errors and oversized bodies are quarantined before any job is inserted. The response contains a quarantine ID and workflow_started: false, not a run ID. Bodies are limited to 16 KiB; oversized quarantine entries retain only a bounded prefix, whose hash is recorded with a truncation flag. Quarantine records are local and have no public retrieval endpoint.

Jobs, results and quarantine are stored in data/runtime/service.sqlite3 by default and excluded from Git. Every SQLite operation opens its own connection. Atomic BEGIN IMMEDIATE transactions prevent two workers from claiming one queued job at the same time. A worker renews its lease and heartbeat. An expired lease can be reclaimed, at most twice in total; a fresh lease token fences late results from an old worker. This is at-least-once execution after a crash, not exactly-once computation. SQLite is a local queue prototype, not a distributed broker.

A queue capacity of 100 pending/running jobs gives HTTP 503 plus Retry-After when full. Unexpected workflow errors produce a FAILED record with a sanitized exception type. Structured API/worker logs carry correlation/run IDs, never request bodies or API keys. Full tracing, Prometheus metrics, authentication, cancellation, idempotent submissions and distributed reliability remain future work.

## Run locally in PowerShell

From the project root, start the API:

```powershell
& '.\.venv\Scripts\python.exe' -m uvicorn api:app --app-dir src --host 127.0.0.1 --port 8000
```

In another PowerShell window in the same folder, start a worker:

```powershell
& '.\.venv\Scripts\python.exe' '.\src\worker.py'
```

Both processes must use the same TRIAGE_DB_PATH if you override it. Default mode is stub; TRIAGE_MODE may be stub or deterministic. Neither makes hosted model requests. Initial local retrieval requires the existing v2 index and cached embedding model. No database rebuild is needed for this service stage.

Submit a synthetic policy question:

```powershell
$body = @{ petition = 'Synthetic demo: what are the attendance condonation requirements?'; synthetic = $true } | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/petitions' -ContentType 'application/json' -Body $body
Invoke-RestMethod -Uri ('http://127.0.0.1:8000' + $run.poll_url)
```

Stop a foreground API/worker with Ctrl+C. This stage is a loopback-only local prototype without authentication; do not expose it to a network or submit real student records. Jobs can be accepted while the worker is offline and remain QUEUED until it returns. /ready makes that condition visible.

## Validate together

```powershell
& '.\.venv\Scripts\python.exe' '.\src\check_project.py' --service
```

This runs existing regressions, API/queue tests with injected runners, and a real local HTTP test using separate API and worker processes with hosted credentials explicitly disabled. The HTTP smoke includes rejection/quarantine without a job, cited stub results, unsupported escalation and result persistence after an API restart. It creates only a temporary test queue under work/ and shuts down its child processes. Reports are written to evaluations/. No Groq requests are needed.

The service result is a preliminary human-review aid. SUCCEEDED means processing completed, not that the petition was granted. This stage adds the API/queue and invalid-request quarantine paths; the instructor's container-only deployment, distributed worker/load evaluation, complete injection/toxicity defenses and broader semantic quality evaluation are still incomplete.

Validation on 2026-10-23 passed 54 unit tests, 11 retrieval checks and 4 deterministic workflow cases, plus the local HTTP/separate-worker smoke described above. The HTTP smoke observed QUEUED, RUNNING and SUCCEEDED; its single submit observation is not a p95/SLO result. Reports: evaluations/project_checks.json and evaluations/service_smoke.json. No hosted model requests were made.
