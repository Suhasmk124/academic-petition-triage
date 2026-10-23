# Petition portal and fixed evaluation

## Implemented

FastAPI now serves a buildless HTML/CSS/JavaScript portal at `/`. The same service still provides `/docs`. No JavaScript packages, remote fonts or external assets are required. The interface includes sample petitions, the synthetic-data declaration, input limits, worker connectivity, queue progress, run references, full source quotations, verified page labels, generated-locator notices, supporting-record checklists and human review outcomes. Content is inserted as text, never interpreted as HTML. Polling has request timeouts, bounded connection retries and a manual resume option. A new submission can be made after completion.

The service remains a local prototype without authentication. Its default is the simulated model with real local retrieval and source checks. It does not spend hosted API quota. The interface labels this explicitly. It does not make eligibility decisions. There is no user account, document upload or case-history browser yet; keep the run ID to retrieve a result through the API after refreshing.

## Run locally

From `C:\Sauce\academic-petition-triage`, start the API in one PowerShell window:

```powershell
$env:TRIAGE_MODE = 'stub'
.\.venv\Scripts\python.exe -m uvicorn api:app --app-dir src --host 127.0.0.1 --port 8000
```

In a second window, start the worker:

```powershell
$env:TRIAGE_MODE = 'stub'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe src\worker.py
```

Open http://127.0.0.1:8000/. The cached model may take longer on the first request. Stop each process with Ctrl+C when finished.

## Fixed evaluation

`evaluations/scenarios.json` contains 24 fixed synthetic scenarios: eight attendance, six medical examination, six X-grade/retest and four unsupported requests. Each has an expected status, reviewed clause IDs and PDF pages, authored independently of runtime classification. The dataset hash identifies the exact version in each report.

`src/evaluate.py` runs each scenario through both the deterministic and simulated two-role workflows (48 runs). It checks expected routing, complete provision sets, canonical citations, source quotation fidelity, required human review and absence of final decisions. Supported stub cases must use the two-role path rather than silently falling back. Calls to the hosted adapter are explicitly blocked during evaluation.

The evaluator compares historical vector retrieval (eight chunks, distance cutoff 1.15) with current hybrid retrieval (up to four section groups). It reports complete-clause recall, a page-overlap relevance proxy, returned unit counts and character budgets. Exact full-clause containment counts as a hit; partial clauses do not. Baseline chunks and current citations differ in size, and section grouping changes the context budget, so this compares pipelines rather than isolating a ranker change. Full-context token budgets and prompt A/B are not evaluated.

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe src\check_project.py --service --evaluation
```

This runs the regression tests, focused retrieval checks, workflow smoke checks, isolated HTTP/worker integration and the fixed evaluation. Reports go to `evaluations/`. The evaluator needs both the preserved legacy and current Chroma collections; the HTTP smoke test uses a disposable queue. Evaluation-metric tests verify rejection of altered pages, invented IDs, unsupported claims and fabricated quotations. Empty outputs do not receive perfect faithfulness scores.

## Results and limits

The initial fixed run passed all 48 workflow cases. Macro-average complete-clause recall across 20 supported queries was 49.17% for the historical pipeline and 100% for the current one. The page-overlap proxy was 43.84% and 58.48%, respectively. These measures are local regression results, not proof of semantic relevance, generalization or academic correctness. See `evaluations/fixed_suite_report.json` for per-case results and budgets.

The combined check passed 60 tests, 11 focused retrieval checks, four deterministic smoke cases and the real HTTP/worker integration. Manual browser checks covered all three supported petition types, unsupported escalation, declaration/blank-input handling, expanded citations and a 390-pixel mobile layout without horizontal overflow. See `evaluations/browser_smoke.json` and `outputs/portal-preview.png`. Browser network interruption/reconnection paths, a full accessibility audit and cross-browser coverage remain untested.

The dataset was written after implementation and is not a held-out benchmark. Unsupported examples test the narrow pilot classifier, not reliable general out-of-corpus detection. Simulated extractive statements make exact-source faithfulness measurable; they cannot establish natural-language entailment or hosted model accuracy. The previously observed hosted semantic errors remain relevant. Prompt A/B, broader semantic evaluation, injection/toxicity defenses, feedback, Docker/distributed workers and observability remain planned. This stage advances A8 and part of L3; it does not complete all instructor requirements.
