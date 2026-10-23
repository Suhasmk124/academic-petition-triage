# CONTEXT HANDOFF — Academic Regulation and Student Petition Triage Service

Last updated: 2026-10-23
Purpose: Carry this file into a new ChatGPT conversation/model and continue implementation from the exact current state.

---

## 1. Instructions for the next assistant

Act as a practical technical project mentor. The user is working on Windows PowerShell and prefers step-by-step instructions, usually one concrete task at a time. Provide complete replacement files when asked; the user explicitly prefers “change the code and give back the whole thing” rather than scattered patches.

Do not restart the project or reinstall packages unless needed. Inspect the existing files before proposing changes whenever possible. Be clear about:
- what is already implemented and tested,
- what is only a scaffold,
- what remains to be built,
- commands to run from the project root,
- expected output and how to troubleshoot it.

The project is for an ML System Design & AgentOps course. Keep instructor requirements in view. Do not claim unimplemented features are complete. The final system must support human review: it must not independently make final academic decisions.

## 2. Project brief and goal

Project title: **Mini Project 15 — Academic Regulation and Student Petition Triage Service**  
Course: ML System Design & AgentOps (UE24AM342AA5)  
Team size: 2–3  
Project level: Jackfruit Level 3, 10 marks.

Build a multi-agent service that accepts an academic petition, validates it, classifies/extracts key entities, retrieves applicable base provisions and modifying/condonation provisions, creates an evidence-grounded eligibility position with chapter/clause citations, and routes the case to:
- grant-under-provision / recommend handling under a provision,
- refer to committee / human officer,
- reject only when clearly supported by a cited clause,
while never making the final decision on behalf of the examination officer.

Required/important brief items captured from prior discussion:
- A1: LangGraph or CrewAI; retrieval must be a tool chosen/used by an agent; at least 3 tools; bounded loops/tool calls.
- A2: at least two genuinely distinct agents with defined hand-off and failure handling.
- A3: verify each answer/citation against retrieved text; re-search or escalate when unsupported.
- A4: asynchronous FastAPI service with run ID/status polling and queue/task runner.
- A5: timeouts, bounded retries with exponential backoff, circuit breaker, fallback.
- A6: metrics per agent (success, steps/tool calls, latency, retries, uptime).
- A7: Docker Compose scale workers to 3 and measure throughput/p95 with stub LLM.
- A8: simple web client.
- L1: LangChain/LlamaIndex and FAISS/Chroma; document chunking/embedding and support re-embedding without rebuilding whole index.
- L2: versioned prompts; compare two prompt variants.
- L3: 20+ fixed evaluation scenarios with expected outcomes/passages; TruLens or equivalent measures for groundedness/context relevance/faithfulness/hallucination; before/after comparison.
- L4: prompt injection defense, output filters, toxicity detection for input/output.
- L5: token/cost attribution per step and run.
- L6: feedback endpoint and quality sampling.
- D1: contracts/schema validation and quarantine invalid records; invalid request must not start agent.
- D2: idempotent corpus pipeline, CLI, freshness/source versions/chunk counts/throughput metrics.
- D3: at least 4 Docker Compose services, clean clone runs with health checks, nothing outside containers.
- D4: `.env.example`; no credentials/endpoints/model IDs embedded in repository.
- D5: structured logs, correlation IDs, OpenTelemetry/Jaeger or Tempo, Prometheus, Grafana; reconstructable runs.
- D6: declare p95 SLO before measurement; Locust with stub model service realistic delays; report RPS/p50/p95, concurrency, failures, bottleneck.
- D7: caching/rate limit and measured p95/cost effect.
- D8: runbook for 2 failure modes and a real incident log entry.
- Demo checklist: clean compose up; valid cited recommendation; trace; malformed request quarantined/no run; out-of-corpus escalates; unsupported answer caught/re-search/escalate; injection blocked; circuit breaker; Locust and worker scaling; difficult case.
- Do not attempt every advanced feature before a working end-to-end path. Build the end-to-end core first, then evaluation and operational requirements.
- Use synthetic petitions only, no real student records.

## 3. Selected corpus and authoritative rules identified

Corpus selected: IISc Undergraduate Handbook 2025–26, local file:
`data/raw/UG-HandBook-25-26.pdf`

Extracted text and pages:
- `data/processed/handbook_text.txt`
- `data/processed/handbook_pages.json`

PDF has 180 pages extracted.
Relevant passages identified:
1. PDF page 37, printed page 34, Chapter 8, Section 8.1 “Attendance”:
   - Attendance in all classes must be at least 80%.
   - Below 80% at mid-term: student will not be allowed to take the mid-term examination.
   - Semester attendance below 80%: student is debarred from terminal examination.
   - Shortage may be condoned by the Dean only in exceptional circumstances.
   - 80% mandatory attendance may be condoned for medical issues with supporting documents, including a medical certificate issued by the CMO, Health Centre, IISc, when applying for medical leave.
   - Need to inspect the full extracted passage for the precise medical application deadline (the currently retrieved chunks often truncate the rule).
2. PDF page 25, printed page 22, Section 5.6 “Terminal Examination”:
   - Terminal exam attendance is compulsory.
   - Medical absence certified by the Institute CMO may be condoned, and student may be permitted a substitute examination within a prescribed period.
   - The student must apply for medical leave on SLCM within 7 days of recovery and upload the medical certificate on SAP (verify the complete clause from the full source before using as final).
3. PDF page 26, printed page 23, Section 5.7(C) has provisions about an X grade for missing final exam due to medical reasons, CMO-attested certificate, instructor upload/justification, and retest/grading deadlines.
4. PDF page 37 also contains Section 8.2 “Leave Rules”. One clause says absence not exceeding two weeks in a semester due to unavoidable reasons may be condoned by the Dean of Undergraduate Studies if satisfied with the explanation. Do not confuse this with the separate attendance rule; don't overgeneralize who has authority.
- Handbook is an UG Handbook 2025–26, and separate exam bye-laws may exist; don't overclaim beyond the actual corpus.

## 4. Windows environment and current folder structure

User works in Windows PowerShell.

Project root:
`C:\Sauce\academic-petition-triage`

Created directories:
```
academic-petition-triage/
  data/
    raw/
    processed/
    chroma_db/
  src/
  tests/
  evaluations/
  logs/
```

Virtual environment:
- `.venv`
- Activate from project root:
  `.\.venv\Scripts\Activate.ps1`

Installed packages (successfully installed):
- `pymupdf`
- `langchain-core`
- `langchain-text-splitters`
- `langchain-chroma`
- `langchain-huggingface`
- `sentence-transformers`
- `chromadb`
- `langgraph` (version observed as 1.2.16)
- Dependency stack includes CPU PyTorch.

Embedding model: `sentence-transformers/all-MiniLM-L6-v2`  
Chroma collection: `iisc_academic_regulations`  
Chroma persistent DB directory: `data/chroma_db`

Warnings observed:
- Hugging Face unauthenticated requests warning: harmless for current local prototype; no HF token required to proceed.
- Windows symlink/cache warning at model install: harmless, reduced cache efficiency only.
- Retrieval distance is a vector distance, not a probability/confidence; lower is closer for current metric, but relevance must still be checked.

## 5. Files implemented so far

### `extract_pdf.py` (project root)
Uses PyMuPDF to extract PDF page text and writes:
- `data/processed/handbook_text.txt`
- `data/processed/handbook_pages.json`
Extraction ran successfully and extracted 180 pages.

### `src/index_corpus.py`
Implemented corpus indexing:
- Reads `handbook_pages.json`
- Creates LangChain `Document` objects with source, PDF page, printed page and chapter metadata.
- Splits text using `RecursiveCharacterTextSplitter`, `chunk_size=1000`, `chunk_overlap=150`.
- Uses `HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")`.
- Stores chunks in Chroma collection `iisc_academic_regulations`.
- Batch adds 64 chunks.
- Tests retrieval for an attendance/medical query.
- Successfully indexed 496 chunks.
Potential issue: printed page metadata is approximated as `pdf_page - 3`; chapter metadata is assigned per page using simple text check and is not reliable for all chunks. Must fix before using for citations.

### `src/test_retrieval.py`
Queries:
- minimum attendance and consequences below threshold
- medical condonation
- medical certificate and deadline
It ran successfully. Relevant results usually include PDF page 37, but some irrelevant passages appear and deadline query does not consistently retrieve full text. Need improve chunking/retrieval and evaluate.

### `src/retrieval.py`
Current implementation is a LangChain `@tool` around Chroma:
- loads `HuggingFaceEmbeddings` model
- loads persisted Chroma collection
- `search_regulations(query: str)` calls `similarity_search_with_score(query, k=8)`
- provisional `max_distance = 1.15`, skips candidates with greater distance
- returns source, PDF page, distance, and text for each passage
- returns `NO_SUFFICIENT_EVIDENCE` if nothing survives
- `__main__` tests three queries.
Observed behavior:
- Attendance query retrieves PDF page 37 with 80% rule.
- Medical condonation query retrieves PDF page 37, sometimes irrelevant page 60, and other Section 8.2 chunk.
- Deadline query retrieves Section 5.6 at PDF page 25 and may return other irrelevant passages.
- Provisional distance threshold does not ensure evidence correctness. Should tune using fixed eval scenarios, not assume threshold alone verifies claims.
- Page 37 chunks truncate after “applying for medical leave of absence”; need ensure complete clause text available for the application deadline.

### `src/workflow.py`
Current code is the full version provided most recently in prior chat. It imports:
```
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from retrieval import search_regulations
```
Defines `PetitionState` TypedDict:
- `petition`
- `evidence`
- `assessment`
- `verification`
- `searches`
- `status`

Nodes:
- `investigate(state)`: calls `search_regulations.invoke`; if searches already > 0, uses a more focused query. Returns evidence, incremented search count, generic preliminary assessment text.
- `check_attendance_evidence(evidence)`: keyword checks for `"80%"`, `"condoned"` and `"medical"`, and `"cmo"`.
- `verify(state)`: if no evidence / insufficient evidence marker, retry if searches <2 else escalate; otherwise runs keyword checks and sets status to `REVIEW_REQUIRED` if checks pass, retry/escalate if checks fail.
- `route_after_verification`: if status is `RETRY` and searches <2 routes back to `investigate`, else ends.
- graph edges: START -> investigate -> verify -> conditional back to investigate or END.
- sample petition: “My attendance is 72%. I missed classes because of a medical issue. What does the handbook say about attendance condonation and required medical evidence?”
- `app.invoke` prints status, search count, assessment, verification and evidence.

Current latest run output:
```
STATUS: REVIEW_REQUIRED
SEARCHES PERFORMED: 1
PRELIMINARY ASSESSMENT:
Preliminary assessment only. Identify the applicable rule, requirements, exceptions, and missing information. Do not make a final administrative decision.
VERIFICATION:
Required attendance evidence checks passed. The retrieved text includes the attendance threshold, medical-condonation provision, and CMO requirement. Individual claims and citations still require detailed verification. No final administrative decision was made.
```
Retrieved relevant evidence:
- PDF page 37, Section 8.1, with 80% threshold, consequences, Dean exceptional circumstances, medical condonation and CMO certificate.
- PDF page 25, Section 5.6, with terminal exam medical absence clause.
- PDF page 60, medical facilities content, irrelevant.
This output is expected for the current prototype.

Important architecture truth:
- These are currently two LangGraph nodes/functions, not two genuinely independent LLM agents.
- No LLM provider/model has been configured.
- No actual natural-language final assessment is generated yet.
- Verification is keyword-based, not claim-level citation validation.
- Retry path exists but only activates if the simple checks fail; the current petition passes on first search.
- No API/queue, schema validation, prompt-injection guard, evaluation suite, Docker, observability, load testing or frontend implemented yet.

## 6. Commands user has already run successfully

From PowerShell in `C:\Sauce\academic-petition-triage` with `.venv` activated:
```
python extract_pdf.py
python src\index_corpus.py
python src\test_retrieval.py
python src\retrieval.py
pip install langgraph
python src\workflow.py
```

Most recent successful command:
`python src\workflow.py`

No current error to fix. Do not make user reinstall packages.

## 7. What we should do next (recommended order)

Continue from current working state. Do not jump straight to Docker/observability.

### Immediate priority A: inspect complete source clauses and improve chunking
- Use `handbook_pages.json` to print complete text for PDF pages 25, 26 and 37.
- Confirm exact application deadlines, SAP/SLCM requirements and the precise source clause.
- Improve indexing to split around section/clause boundaries or use a chunk size/overlap that keeps the relevant clause intact.
- Make page/chapter/section metadata reliable.
- Add a targeted retrieval test that expects Section 8.1 on PDF page 37 for attendance and Section 5.6 on PDF page 25 for terminal medical absence.
- Consider retrieval of full pages or clause-level chunks rather than relying only on embedding similarity.
- Rebuild Chroma only after updating indexer; it currently deletes and rebuilds the collection each run, which is not yet idempotent/partial-refresh capable.

### Immediate priority B: replace generic workflow with structured evidence assessment
- Use structured state/output for findings, claims, citations, missing evidence, routing recommendation and reasons.
- Explicitly distinguish:
  - `GRANT_UNDER_PROVISION` / recommendation to process under provision,
  - `REFER_TO_COMMITTEE` / human review,
  - `REJECT_UNDER_PROVISION` only if an explicit cited clause supports it,
  - no final approval/rejection by the AI.
- Ensure unsupported/out-of-corpus petitions escalate.
- Citation should include handbook title/version, section, PDF page, printed page only if verified, and exact supporting quote.
- Keyword check should not be presented as general citation verification.

### Priority C: genuinely distinct agents and tools
- Choose a free/local model provider only after clarifying environment and what can be installed. User’s current embeddings run locally; no chat LLM is installed/configured.
- Use two distinct agents or LLM-backed roles with explicit prompts and hand-off:
  1. Investigation agent uses retrieval tool(s) to find base provisions and modifying/condonation clauses.
  2. Verification agent checks each claim and citation against exact evidence; can trigger one re-search or escalation.
- Ensure at least three agent-selectable tools as the brief requires (e.g. search regulations, fetch exact clause/page, check corpus coverage/citation).
- Bound calls and retries.

### Then continue to:
1. Pydantic request/response contracts and quarantine invalid petitions (invalid requests must not start workflow).
2. FastAPI async submission, run ID, status polling, queue/task runner.
3. Prompt versioning, prompt A/B comparison, 20+ fixed evaluation cases and groundedness/faithfulness/context relevance/hallucination metrics.
4. Prompt injection and input/output filters.
5. Per-step token/cost attribution, feedback endpoint and quality sampling.
6. Retry/backoff, timeout, circuit breaker, fallback.
7. Structured logs, correlation IDs, OpenTelemetry/Jaeger or Tempo, Prometheus and Grafana.
8. At least four Docker Compose services with health checks, worker scaling to three, stub LLM service, Locust load tests and p95 SLO.
9. Cache/rate limit with measured effects; runbook and incident log; simple web client.
10. README, architecture diagram, test results, demo checklist.

## 8. Suggested instructor explanation (current status)

“Our prototype has completed PDF ingestion, embedding-based retrieval and a basic LangGraph orchestration flow. We extracted 180 handbook pages, indexed 496 overlapping chunks in ChromaDB using `all-MiniLM-L6-v2`, and verified that attendance queries retrieve Section 8.1 from the handbook. We have a LangGraph investigation node and a verification node, with bounded retries and review/escalation states. At present, the verification is keyword-based, so claim-level citation checking and genuinely independent LLM agents are still work in progress. Our next priority is accurate clause-level retrieval and evidence verification, followed by FastAPI, evaluation and operational requirements.”

## 9. Start-here instruction for the next chat

First acknowledge this handoff and continue from the current state. The next practical task should be to inspect complete handbook text for PDF pages 25, 26 and 37, then fix clause-aware chunking/metadata and retrieval tests. Give concrete PowerShell commands and complete file replacements where helpful. Do not ask the user to restate project context and do not claim advanced requirements are complete.
