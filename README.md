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
- Quote-presence and source-integrity checks. These do NOT check claim entailment.
- A LangGraph investigation node and verification node, with at most two searches and review/escalation states. Existing workflow output remains a placeholder assessment with attendance-specific keyword checks.
- Seven focused retrieval cases and four quotation/integrity checks in src/test_retrieval.py.

These are Python workflow nodes, not two independent LLM agents. No chat LLM is configured. The current graph calls only search_regulations; having three tools defined does not satisfy the requirement for agent-selected tool use.

## PowerShell commands

Use the existing Python 3.11 virtual environment. No package reinstall is required for the current project.

```powershell
.\.venv\Scripts\Activate.ps1
python src\index_corpus.py --preview
python src\index_corpus.py --apply
python src\test_retrieval.py
python src\workflow.py
```

The default indexer mode is preview. --apply updates iisc_academic_regulations_v2 without deleting the legacy collection. The generated database is ignored by Git and must be built locally after pulling this change. The cached embedding model was used for validation; a clean-machine dependency/model installation has not been tested.

Retrieval checks write evaluations/retrieval_smoke_report.json. This small regression suite is not the required 20+ scenario evaluation. The no-overlap gate only rejects queries with no matching lexical terms; reliable out-of-corpus detection is still planned. A matching quote does not prove that a generated claim follows from it, or that a petition is eligible.

## Source and history

Corpus: IISc Undergraduate Handbook 2025-26 in data/raw/. This is third-party source material; the repository does not grant rights over it. Extracted text is in data/processed/.

- docs/academic_petition_triage_context_handoff.md: historical context and instructor requirements.
- docs/proposals/index_corpus.py: the original proposed indexer, retained as historical material. The active maintained implementation is now src/index_corpus.py.
- docs/clause_retrieval_update.md: change scope, validation and limitations.

The original C:\Sauce project folder is not modified by the assistant's writable working-copy tests. Pull the committed source changes and run --apply there to create its local v2 index.

## Remaining instructor requirements

Structured claim-level assessments and entailment verification; two independent LLM-backed agents with agent-selected tools; request contracts and quarantine; asynchronous FastAPI and queue; prompt versions and A/B evaluation; 20+ fixed evaluation scenarios and groundedness/faithfulness metrics; injection and output defenses; timeout/retry/backoff/circuit breaker; token/cost attribution; feedback; tracing, metrics and dashboards; Docker Compose and worker scaling; stub model service and Locust/SLO measurements; caching/rate limiting; runbooks, incident log and web client.

Configuration still contains the prototype's embedding-model name; the environment-based configuration requirement is not complete. Use synthetic petitions only. Do not commit student records, credentials, virtual environments or generated databases.
