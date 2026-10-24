# Deployment and verification

Use fictional petitions only. Every route is a conditional recommendation for an officer; supplied facts remain unverified. The handbook is third-party source material and this repository grants no rights over it.

## Start from a clean clone

Docker Desktop must be running in Linux-container mode. On Windows, enable WSL 2 and virtualization and restart after installation. No host Python installation is required for the application:

```powershell
git clone https://github.com/Suhasmk124/academic-petition-triage.git
Set-Location academic-petition-triage
.\scripts\start.ps1
```

The first build downloads packages and public embedding weights. Later starts reuse image/model/index volumes. Do not copy a teammate's `.env`, `.secrets`, runtime database or student records. Generate separate local keys. The starter uses a container to generate keys when the project virtual environment is absent. Linux/macOS users can run `docker run --rm -v "${PWD}:/app" -w /app python:3.11-slim python scripts/configure.py`, then `docker compose up --build -d --scale worker=3`.

Open the portal at http://127.0.0.1:8000 and enter the local key from `.secrets/triage_key`. This key protects a shared demonstration workspace; it is not individual-user authorization. Browser sessions expire and use HttpOnly/SameSite cookies. Host ports bind to loopback. Exposing the service publicly requires TLS, individual identities and data-access controls.

## Services and evidence

The one-shot indexer extracts and hashes the PDF, incrementally embeds changed records and initializes a reproducible generic-chunk comparison collection. API and workers share a durable SQLite queue on one Docker host. Redis shares TTL cache and rate limits. The separate simulated model service uses real retrieval/source checking and realistic per-step delay. Three worker containers claim leases atomically, renew them and reclaim bounded abandoned work. This is single-host worker scaling, not a distributed SQLite deployment.

Jaeger is at http://127.0.0.1:16686; Prometheus at http://127.0.0.1:9090; Grafana at http://127.0.0.1:3000 (user `admin`, local password in `.secrets/grafana_key`). The provisioned dashboard shows traffic, latency, queue depth, workers, role activity, tools and tokens. Run IDs and correlation IDs link structured logs to trace IDs. Trace context crosses the queue and stub HTTP boundary. Spans omit petition text and keys.

```powershell
docker compose ps
docker compose exec -T api python src/check_project.py --evaluation
.\.venv\Scripts\python.exe scripts/verify_stack.py --observability
.\.venv\Scripts\python.exe scripts/verify_failures.py
.\.venv\Scripts\python.exe scripts/benchmark.py --seconds 60
docker compose logs --tail 50 api worker stub
```

Host verification scripts use `httpx`; publication audit also uses `python-dotenv`. Application execution and regression/evaluation run inside containers. The optional host drivers coordinate Docker and local HTTP; they do not run the application outside containers. Do not run failure/load drivers concurrently. Each temporarily changes workers/cache/rate settings and restores the ordinary three-worker deployment.

## Model usage and cost

Compose defaults to simulation with zero hosted requests. The two roles have distinct versioned prompts and model-selected tools. Simulation validates orchestration and source contracts but does not establish language-model reasoning quality. Real hosted testing is separately recorded, including unsuccessful attempts. Hosted service use requires explicit `TRIAGE_ALLOW_HOSTED=true`, `TRIAGE_MODE=hosted`, and local provider configuration; keys are never copied into the image by default. Keep routine demonstration/load runs in stub mode to preserve free quota. No automatic provider/model switch or paid fallback exists.

Hosted usage reports provider token counts when available; billed cost is unknown unless supplied, not inferred as free from a success response. Stub tokens are character-based estimates and stub cost is zero. Cached responses clear current-run usage and report avoided model calls. Cache keys include mode, input, corpus, prompts and source code; the worker rechecks output before reuse and computes each run's conditional position from its own facts.

## Measurements and acceptance

`load/slo.json` declares submission p95 <=750 ms, completion p95 <=10 seconds and completion failures <=1%, for 10 concurrent clients and 60 seconds, before measurement. Locust records business completion separately from submission/poll requests. The driver compares one worker, three workers, and three workers with cache; it records actual cache hits and avoided simulated calls. Billing savings on a free simulated model are zero dollars. Do not describe this as a paid-provider cost experiment or linear scaling proof.

Authoritative result files are in `evaluations/`. A report is evidence only for its recorded deployment/version; `native_stack.json` does not prove Docker readiness. `hosted_postguard_smoke.json` must show provider completion, not deterministic fallback, to count as live validation. Quote fidelity and canonical-statement identity are conservative extractive tests, not general semantic entailment. `semantic_challenges.json` explicitly reports valid paraphrases rejected by this policy.

Stop with `docker compose down`. Keep volumes to retain fictional runs/index/models. Do not use `down -v` during recovery; it destroys that deployment's persisted state.
