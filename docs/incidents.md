# Incident log

## 2026-10-23 — hosted verifier accepted misleading medical-condition claims

Evidence: `evaluations/hosted_live_smoke.json` and `docs/hosted_agents.md`. This records an observed prior run, not a newly performed live model test.

A hosted investigation/verification handoff completed its tool calls, but human source inspection found semantic mistakes the verifier accepted: confusing the SLCM leave-application step with SAP document upload, and weakening the certificate-issuer requirement. The affected synthetic output could mislead a reviewer. No final academic decision was made.

Detection came from comparing the claims with the full handbook provisions. Exact-quotation checks had passed; they established that the quoted source existed, not that the generated statement preserved its conditions. This exposed a limit in the LLM verifier and the interpretation of quote-check success.

Containment and remediation: preserve human review, add narrow condition guards and regression fixtures, and keep routine service execution in local simulated/extractive modes. The 2026-10-24 worker gate additionally rejects non-extractive or altered source claims in those local modes. Hosted semantic accuracy and a live post-guard validation remain unproven; the new local tests do not close that gap.

Follow-up: use a held-out semantic challenge set and prompt A/B evaluation before enabling hosted service inference. Report claim entailment separately from source integrity and simulated workflow success. Keep the observed failure visible in the demo/limitations rather than counting successful tool calls as academic correctness.
