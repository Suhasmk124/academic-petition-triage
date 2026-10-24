# Incident log

## 2026-10-23 — hosted verifier accepted misleading medical-condition claims

Evidence: `evaluations/hosted_live_smoke.json` and `docs/hosted_agents.md`. This records an observed prior run, not a newly performed live model test.

A hosted investigation/verification handoff completed its tool calls, but human source inspection found semantic mistakes the verifier accepted: confusing the SLCM leave-application step with SAP document upload, and weakening the certificate-issuer requirement. The affected synthetic output could mislead a reviewer. No final academic decision was made.

Detection came from comparing the claims with the full handbook provisions. Exact-quotation checks had passed; they established that the quoted source existed, not that the generated statement preserved its conditions. This exposed a limit in the LLM verifier and the interpretation of quote-check success.

Containment and remediation: preserve human review, add narrow condition guards and regression fixtures, and keep routine service execution in local simulated/extractive modes. The 2026-10-24 worker gate additionally rejects non-extractive or altered source claims in those local modes. Hosted semantic accuracy and a live post-guard validation remain unproven; the new local tests do not close that gap.

Follow-up: use a held-out semantic challenge set and prompt A/B evaluation before enabling hosted service inference. Report claim entailment separately from source integrity and simulated workflow success. Keep the observed failure visible in the demo/limitations rather than counting successful tool calls as academic correctness.

## 2026-10-24 — hosted tool-output formatting failed closed

Several real free-provider attempts returned HTTP 200 tool selections followed by schema failures or HTTP 400 tool parser failures. One attempt included a function name with an unexpected channel suffix; others could not parse generated quotation arguments. Every failed attempt fell back without accepting the generated draft. Reports retain the failures rather than counting fallback as hosted success.

The strict investigator now selects evidence IDs instead of copying long quotations. The server attaches complete canonical excerpts. The independent verifier submits short typed per-claim decisions after using its source tool. A lowercase `submit_result` function replaces the ambiguous `JSON` output-function name. Schema correction is bounded by the original turn limit; source requirements cannot be bypassed. Baseline protocols remain available for the historical comparison.

Recovery evidence: `evaluations/hosted_postguard_smoke.json` records a real final strict v4/v5 pass in four HTTP requests, three complete canonical claims and both required role tools. Nineteen HTTP attempts were made in the post-restart debugging session in total, including retained failures; no 429 retry, model switch or paid fallback was used. Simulation remains the default to protect free quota. This one-case acceptance closes the observed protocol failure, not general semantic accuracy.

## 2026-10-24 — deployment verification timing and fixture isolation

The first observability assertion read a partially exported trace containing only the HTTP span. Verification now waits for all required worker/stub/role spans, and uses a fresh fictional input so a cache hit cannot substitute for tracing the model path. Real Jaeger/Prometheus/Grafana acceptance then passed.

Containerized scripted tests also inherited the strict deployment prompt setting despite using baseline fixtures. Fixtures now explicitly select their intended version; standalone integration child processes clear shared authentication/cache/Redis/stub settings. These are test-driver corrections, not disabling controls on the deployed service. Final regression and deployment reports record the rerun.
