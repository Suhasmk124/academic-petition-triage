# Instructor requirement map

Implementation is separate from acceptance evidence. Consult the JSON reports rather than treating this table as a test certificate. Historical handoff files describe earlier stages and do not override current code or direct user requests.

| Requirement | Implementation | Verification and limits |
|---|---|---|
| A1 framework, agent-selected retrieval, 3 tools, bounded loops | LangGraph, separate role histories; search, exact-clause fetch, batched quote check; 6 turns/tools per role and 2 passes | Scripted protocol tests plus separately recorded live results. `submit_result` is an output channel, not a fourth source tool. |
| A2 distinct agents and handoff | Investigator drafts evidence IDs; independent verifier checks complete coverage; failure fallback | `test_hosted_agents.py`; live completion must be proven by `hosted_postguard_smoke.json`, never by fallback. |
| A3 source verification and re-search | Canonical page hashes/offsets/metadata, quote tool, complete statement identity in strict mode; one re-search, then escalate | 11 retrieval checks, fixed suite, 22 semantic challenges; extractive identity is not general entailment. |
| A4 async API and queue | FastAPI submission, durable run IDs/status/results, SQLite leases and separate workers | Real HTTP/restart integration and deployed acceptance. Single Docker host. |
| A5 reliability | HTTP deadlines, bounded exponential retries, circuit breaker, isolated fallback deadline, abandoned lease recovery | Unit tests plus `deployed_failures.json` for real outage/open/recovery. |
| A6 agent metrics | Per-role success, model/tool calls, latency, retries, reported/estimated tokens; uptime, structured logs | `/metrics`, persisted result metadata, provisioned dashboard. |
| A7 three workers and throughput | Compose worker replicas, separate warmed stub service, Locust completion measurements | `load_report.json` and round CSVs; report actual scaling, not assumed linear speedup. |
| A8 client | Responsive petition desk, conditional position, complete citations/PDF links, progress/recovery, feedback and authentication | Browser QA screenshot and deployed functional checks. |
| L1 retrieval and incremental embedding | LangChain, local public embeddings, persistent Chroma; generic and reviewed clause records; stable IDs/upserts | Index reports distinguish changed/unchanged records; exact source metadata reviewed for pilot clauses. |
| L2 versioned prompts and A/B | Retained baseline and strict prompt files; `compare_prompts.py` | `prompt_ab_live.json` has one complete paired case; raw quota-exhausted attempts retained. Tiny sample, not statistical proof. |
| L3 20+ cases and quality metrics | 30 fixed cases, 60 local workflow runs; quote fidelity, passage relevance, required-provision recall and meaning mutations | `fixed_suite_report.json`, `semantic_challenges.json`; explicitly report conservative paraphrase false negatives. |
| L4 injection/output/toxicity controls | Normalization, finite rule sets, schema/tool allowlists, quarantine, canonical output gate | 22 fixed safety cases and regressions. Novel attacks and implicit toxicity can be missed. |
| L5 token/cost attribution | Per-role usage, provider counts or marked simulation estimates; cached runs clear usage | Unknown hosted billed costs stay null; free-plan assertion is not an account billing API check. |
| L6 feedback and sampling | Durable idempotent feedback and metadata-only quality-sample endpoint | API and browser tests. No automatic retraining. |
| D1 contracts/quarantine | Pydantic, size/content guards, invalid submissions never enqueue | Unit, HTTP and deployed invalid/injection checks. |
| D2 corpus pipeline | Preview/apply CLI, PDF/page hashes, explicit source-change acknowledgment, manifest, incremental counts/timing | `ingest.py`, `index_corpus.py`, no-op apply verification. |
| D3 multi-service Compose | Indexer, API, workers, stub, Redis, Jaeger, Prometheus, Grafana; health checks and volumes | Fresh image build and container-only initialization must pass before claiming clean-clone acceptance. |
| D4 configuration/secrets | Blank hosted configuration example; ignored local secrets; image excludes local configuration/runtime | Publication audit of history and current files. Public embedding preset is a backward-compatible local default. |
| D5 observability | Payload-free OTel spans, queue/HTTP propagation, Prometheus and Grafana | `deployed_stack.json` checks actual linked Jaeger spans and Prometheus scrape/Grafana health. |
| D6 declared SLO/load | Versioned predeclared 10-client/60-second SLO; separate business latency and submission measurements | `load/slo.json`, Locust CSVs and `load_report.json`; no changing thresholds to pass a result. |
| D7 cache/rate limits | Shared Redis or standalone SQLite TTL cache/fixed window; canonical revalidation and version fingerprint | Unit TTL/invalidation/window tests, deployed 429, measured cache hit/latency/call effect. |
| D8 runbooks/incident | Worker loss, model outage/circuit, quota/parser issues and source-gate procedures | `runbook.md`, `incidents.md`; preserve observed model mistakes and failed live attempts. |

## Review/demo sequence

1. Clean Compose startup and `/ready`; show three healthy workers.
2. Submit a fictional attendance petition with 85% structured attendance; show conditional processing recommendation and canonical clause, then explain why the officer still decides.
3. Repeat with 70%, no medical absence and no exceptional request; show the conditional restriction. Omit facts or add medical uncertainty to demonstrate referral.
4. Open full source PDF and linked Jaeger trace; inspect both role/tool spans and Prometheus/Grafana.
5. Submit a malformed request and instruction override; show quarantine/no run. Submit an unrelated petition and show escalation.
6. Demonstrate altered-claim detection in the semantic challenge report, including legitimate paraphrases rejected by the strict extractive policy.
7. Show controlled stub outage/circuit/recovery evidence and actual Locust worker/cache results.
8. Explain live-provider evidence, failures, free quota and unknown billing fields separately from simulated operation.
