# Academic Regulation and Student Petition Triage Service

Mini Project 15 for ML System Design & AgentOps (UE24AM342AA5).

A prototype for retrieving academic regulations and supporting human review of synthetic student petitions. The system must never make final academic decisions.

## Current implementation

- PDF extraction of 180 handbook pages with PyMuPDF.
- Chroma indexing with local all-MiniLM-L6-v2 embeddings (496 chunks in the existing local index).
- A LangChain retrieval tool and retrieval smoke-test script.
- A LangGraph investigation node and verification node with a maximum of two searches.
- Keyword checks for the attendance example and review/escalation states.

These are two Python workflow nodes, not two independent LLM agents. No chat LLM is configured. The assessment text is a fixed placeholder, and verification does not yet validate individual claims or citations.

## Repository snapshot

The source files under `src/` are the current working project files as of 2026-10-23. The existing virtual environment and generated Chroma database are excluded; regenerate the database locally when needed.

`docs/proposals/index_corpus.py` is the proposed complete replacement indexer. It has been preview-tested against the corpus and tested with stub embeddings in a temporary database. It has NOT been installed as the active indexer, and semantic retrieval quality has not yet been tested. It adds 13 reviewed clause records, source offsets, verified page labels and incremental updates in a separate v2 collection.

`docs/academic_petition_triage_context_handoff.md` preserves the project context, requirements and previous successful run details. Its status is historical; use the active source and this README to distinguish installed code from proposals.

## Local PowerShell usage

The existing project uses Python 3.11. From the repository root, using an existing environment with the listed dependencies:

```powershell
.\.venv\Scripts\Activate.ps1
python extract_pdf.py
python src\index_corpus.py
python src\test_retrieval.py
python src\workflow.py
```

The active `src/index_corpus.py` deletes and rebuilds its legacy Chroma collection. Do not run it merely to inspect the project. Chroma retrieval requires an index to exist. Initial embedding-model download requires network access. Dependencies are pinned to the versions observed in the existing working environment; a fresh-install reproducibility test is still pending.

To preview the proposed indexer without changing the database:

```powershell
python docs\proposals\index_corpus.py --root . --preview
```

## Corpus and citation review

Corpus: IISc Undergraduate Handbook 2025-26, stored under `data/raw/`. The handbook is third-party source material; no ownership or license grant over it is implied by this repository.

Reviewed PDF pages: 25 (printed 22), 26 (printed 23), and 37 (printed 34).

- Sections 5.6(i) and 8.1(iii): application within seven days of recovery, with the specified supporting documents and SLCM/SAP requirements.
- Section 5.7(C): X-grade evidence, instructor responsibilities and retest deadlines.
- Section 8.2(v) remains separate from attendance condonation under 8.1.
- Section 5.6 prints a cross-reference to 5.5(C), while the X-grade heading is 5.7(C). Preserve and flag the source inconsistency.

Printed-page estimates and chapter labels in the active legacy indexer are not reliable enough for final citations.

## Planned work

- Connect clause-level retrieval and evaluate expected passages.
- Structured evidence assessments and claim-level citation verification.
- Two distinct LLM-backed agents, agent-selected tools and bounded handoffs.
- Request validation/quarantine, asynchronous FastAPI, queue and polling.
- Fixed evaluations, prompt versions, injection defenses and output filters.
- Retries/backoff, timeouts, circuit breaker, metrics, tracing and cost tracking.
- Docker Compose, stub model service, load tests, worker scaling and SLO reporting.
- Feedback, caching/rate limits, runbooks, incident log and web client.

These requirements are not implemented in this snapshot. Use synthetic petitions only; do not commit real student records or secrets.
