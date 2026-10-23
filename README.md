# Academic Regulation and Student Petition Triage Service

Mini Project 15 for ML System Design & AgentOps (UE24AM342AA5).

Retrieve academic regulations and support human review of synthetic student petitions. The system must never make final academic decisions.

## Implemented

- PDF extraction of 180 handbook pages with PyMuPDF.
- Local all-MiniLM-L6-v2 embeddings and Chroma persistence.
- A v2 index of 509 records: 496 general chunks and 13 reviewed clause records.
- Complete clauses for sections 5.6, 5.7(C), and 8.1, plus selected related provisions from 5.7(B) and 8.2. Unreviewed chunks have unknown chapter/section metadata; printed page numbers are verified only for PDF pages 25, 26 and 37.
- Exact source offsets, page hashes, source title/version, verified page labels and generated-locator labels. The source's 5.5(C)/5.7(C) reference inconsistency is preserved and flagged.
- Stable record IDs and incremental upserts. An unchanged repeat run re-embeds zero records. The legacy collection is preserved.
- Hybrid lexical/vector retrieval with reviewed clause preference, linked section evidence and full clause quotations. A single retrieval makes one embedding request and one vector query and returns at most four passage groups.
- Three callable LangChain tools: search_regulations, fetch_exact_clause, verify_source_quote.
- Quote-presence, source-integrity and extractive finding/citation checks. These do NOT check semantic claim entailment or academic eligibility.
- A LangGraph investigation/verification handoff with typed extractive findings, exact citations, supporting-record checklists and human-review reasons. Each finding is bound to canonical source text and citation metadata. One re-search is allowed; repeated failures discard findings and escalate.
- Seven focused retrieval cases and four quotation/integrity checks in src/test_retrieval.py.

The default workflow.py remains deterministic. The separate agent_workflow.py now implements two separately prompted LLM-backed roles with model-selected search/fetch/quote-check tools, bounded handoff and deterministic fallback. One live public-policy tool handoff completed, but a source spot-check found semantic errors the model verifier missed. Narrow guards and regressions now cover those observed errors; post-guard live validation and broad semantic accuracy remain open. Automated agent tests use scripted responses. See docs/hosted_agents.md. Do not claim live A1/A2/A3 completion from stub tests.

## API and background worker

The local service now supports asynchronous submission, run-ID polling, persistent queue/results, invalid-request quarantine and a separate worker. It defaults to a simulated model with real local source checks and makes no hosted API calls. Hosted mode is not enabled through the service. See docs/api_queue_stage.md for commands, payloads and limitations. SQLite is the local queue prototype; Docker and a distributed broker are not implemented yet.

## PowerShell commands

Use the existing Python 3.11 virtual environment. No package reinstall is required for the current project.

```powershell
.\.venv\Scripts\Activate.ps1
python src\index_corpus.py --preview
python src\index_corpus.py --apply
python src\check_project.py
python src\workflow.py
```

The default indexer mode is preview. --apply updates iisc_academic_regulations_v2 without deleting the legacy collection. The generated database is ignored by Git and must be built locally after pulling this change. The cached embedding model was used for validation; a clean-machine dependency/model installation has not been tested.

Retrieval checks write evaluations/retrieval_smoke_report.json. This small regression suite is not the required 20+ scenario evaluation. The no-overlap gate only rejects queries with no matching lexical terms; reliable out-of-corpus detection is still planned. A matching quote does not prove that a generated claim follows from it, or that a petition is eligible.

## Source and history

Corpus: IISc Undergraduate Handbook 2025-26 in data/raw/. This is third-party source material; the repository does not grant rights over it. Extracted text is in data/processed/.

- docs/academic_petition_triage_context_handoff.md: historical context and instructor requirements.
- docs/proposals/index_corpus.py: the original proposed indexer, retained as historical material. The active maintained implementation is now src/index_corpus.py.
- docs/clause_retrieval_update.md: change scope, validation and limitations.

This chat now works directly in C:\Sauce\academic-petition-triage. The active workflow changes are implemented there. See docs/structured_assessment_update.md for scope and limitations. All three route names exist in the contract; only REFER_TO_COMMITTEE is currently emitted. Request text is validated through run_petition before the graph, and API submissions are now validated and quarantined before enqueueing.

## Remaining instructor requirements

Live validation and evaluation of the hosted roles and their semantic entailment judgments; evidence-based recommendations beyond referral; Service authentication and distributed queue hardening; prompt versions and A/B evaluation; 20+ fixed evaluation scenarios and groundedness/faithfulness metrics; injection and output defenses; timeout/retry/backoff/circuit breaker; token/cost attribution; feedback; tracing, metrics and dashboards; Docker Compose and worker scaling; stub model service and Locust/SLO measurements; caching/rate limiting; runbooks, incident log and web client.

Configuration still contains the prototype's embedding-model name; the environment-based configuration requirement is not complete. Use synthetic petitions only. Do not commit student records, credentials, virtual environments or generated databases.
