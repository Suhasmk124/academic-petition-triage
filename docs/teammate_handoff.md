# Teammate setup and LLM context handoff

Academic Regulation and Student Petition Triage Service is Mini Project 15 for ML System Design & AgentOps (UE24AM342AA5). It uses the IISc Undergraduate Handbook 2025–26 to prepare a cited case brief for an academic officer. Use fictional cases and specimen attachments for team testing. The human reviewer makes the academic decision.

## Clone and run

Install Git and start Docker Desktop using Linux containers, or Docker Engine with the current Compose v2 plugin on Linux. The Compose overrides use `!override` and require Compose 2.24.4 or newer. Run these commands from the folder where you want the clone:

```text
git clone https://github.com/Suhasmk124/academic-petition-triage.git
cd academic-petition-triage
docker compose version
```

If you already cloned it, use `git pull --ff-only origin main` from the repo folder on `main`. First startup pulls container images and public embedding weights, then builds the handbook index. Docker runs the application and its Python dependencies.

On Windows, run this in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Showcase
```

On macOS or Linux, run this in a terminal:

```bash
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/app" -w /app python:3.11-slim python scripts/configure.py
docker compose -f compose.yaml -f compose.showcase.yaml build api
docker compose -f compose.yaml -f compose.showcase.yaml up --no-build -d --scale worker=3
```

Open the [showcase](http://127.0.0.1:8003). Wait for **Worker connected**. Sign in with `student`, `reviewer`, or `admin` using `pass@1234` for any showcase role. Sign out to change roles. Submit the example below as student and confirm the fictional-data checkbox. Optional PDF, PNG, or JPEG specimen files can be attached up to 5 MiB.

> My attendance is 74% after a fictional medical absence. Which attendance condonation rules apply, what certificate does the handbook require, and what should I submit for officer review?

Open the inline citations and **Agent activity**. Sign in as reviewer, open the student case, and record a recommendation. Switch back to student to see it.

## Audit, monitoring and stress test

With the showcase running, execute these from the repository root in any shell:

```text
docker compose -f compose.yaml -f compose.showcase.yaml exec -T stub python -m stub_model --demo-audit-retry
docker compose -f compose.yaml -f compose.showcase.yaml run --rm --no-deps load python -m locust -f load/locustfile.py --host http://api:8000 --headless --only-summary -u 10 -r 2 -t 60s --stop-timeout 35
```

The first command deliberately omits two attendance clauses. Expect `RETRY`, then `REVIEW_REQUIRED` after the investigator repairs the packet. The second runs 10 simulated users for 60 seconds against the three workers. Follow workflow p95, queue depth, throughput and failures in [Grafana](http://127.0.0.1:3001/d/petition-triage) using `admin` / `pass@1234`. Check [Prometheus targets](http://127.0.0.1:9091/targets) and paste a case's trace reference after `http://127.0.0.1:16687/trace/` to open its trace. Both commands use zero Groq requests. See the [instructor walkthrough](instructor_showcase.md) for worker scaling and the measured results.

## Turn on live Groq agents

1. Sign in to the [Groq Console](https://console.groq.com/), confirm your organization is on the Free plan, then create your own key under [API Keys](https://console.groq.com/keys). Check [Groq's limits](https://console.groq.com/docs/rate-limits) for your account and model.
2. From the repository root, make a local `.env` only if one does not exist. On Windows run `Copy-Item .env.example .env`, or on macOS/Linux run `cp .env.example .env`. Edit these entries in the local file:

   ```dotenv
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_MODEL=openai/gpt-oss-20b
   LLM_API_KEY=replace_with_your_own_key
   LLM_FREE_PLAN_CONFIRMED=true
   ```

   The live worker uses low reasoning effort. The example model supports tool calls and that setting. The plan flag records your confirmation. Keep `.env` and `.secrets/` local. [Groq API compatibility](https://console.groq.com/docs/openai) · [Tool support](https://console.groq.com/docs/tool-use/overview) · [Reasoning settings](https://console.groq.com/docs/reasoning)
3. On Windows run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Live
   ```

   On macOS/Linux, generate the local secret files with the Docker command in **Clone and run** if you skipped the showcase, then run:

   ```bash
   docker compose -p academic-petition-private -f compose.yaml -f compose.private.yaml build api
   docker compose -p academic-petition-private -f compose.yaml -f compose.private.yaml up --no-build -d worker jaeger
   ```

4. Open the [live desk](http://127.0.0.1:8002). Sign in as `admin` with the contents of `.secrets/private_triage_key`. Create student and reviewer accounts with distinct passwords of at least 12 characters, then sign in as student. Submit one fictional case to check **Live model response used** and the auditor’s verdicts. If Groq returns a rate-limit or compatibility error, inspect the status in the brief and use the showcase for repeated runs.

Live mode sends a fixed question for the detected category and the public handbook excerpts. Petition text, facts, and attachments stay local. Attachments are stored for officer inspection. Hosted usage is capped at six request attempts per run, so re-research can exhaust the budget and use local fallback. See the [private workspace walkthrough](private_workspace.md) and [hosted workflow](hosted_agents.md).

## Verify and stop

```text
docker run --rm academic-petition-triage:local python -m unittest discover -s tests
docker compose -f compose.yaml -f compose.showcase.yaml ps
docker compose -f compose.yaml -f compose.showcase.yaml stop
docker compose -p academic-petition-private -f compose.yaml -f compose.private.yaml stop
```

Use the stop command for the stack you started. Stopping preserves the generated index, model cache and local cases. For a startup failure, inspect the relevant Compose logs for `indexer`, `api`, and `worker`. For a port conflict, stop the process using the port before retrying. Adding a key to `.env` only enables calls when you start the live stack.

## Context for the receiving LLM

Start with the teammate's request and inspect their actual checkout. This file provides context. [The original handoff](academic_petition_triage_context_handoff.md) records an earlier project stage. Use [README](../README.md) and the [instructor requirement map](requirements.md) for current scope.

- **Data flow.** FastAPI validates/authenticates input and enqueues a durable SQLite job. A leased worker calls the simulated model service or the isolated hosted workflow. LangGraph passes the investigator's evidence IDs and canonical excerpts to the source auditor. A bounded retry handles a repairable gap. The final source gate validates findings before persistence and client display.
- **Retrieval.** Chroma and the local embedding model index the included IISc UG Handbook PDF. The reviewed pilot clauses focus on PDF pages 25, 26 and 37. Preserve verified page and clause locators, exact quotations, SAP/SLCM wording and the distinction between source fidelity and eligibility.
- **Implementation map.** `src/agent_workflow.py` defines the handoff and tool permissions. `prompts/investigator_v5.txt` and `prompts/verifier_v6.txt` define the active strict roles. `src/api.py`, `src/job_store.py`, and `src/worker.py` cover the request, queue and worker. `src/web/` is the portal. `load/` and `deploy/` contain the stress workload and monitoring config.
- **Verification.** The audited snapshot passed 115 automated tests and Docker API cases for attendance, terminal medical absence and X-grade retests. The earlier live Groq result used prompts v4/v5. The current v5/v6 role split and retry were verified with simulation. Check actual local startup and browser behavior before reporting success on a teammate's machine.
- **Boundaries.** An academic officer retains decision authority. The pilot uses local roles, a single Docker host, and limited rule and source checks. The showcase uses preset credentials and fictional data. The live desk uses separate generated credentials and records. Public GitHub clone access and collaborator push access are separate permissions.
