# Hosted roles and free-tier development

The default Compose service uses a simulated model with real retrieval/source tools. It makes zero hosted calls. Hosted use requires explicit local opt-in and credentials; no paid fallback or automatic model/provider switch exists.

## Current protocol

LangGraph runs separately prompted investigator and verifier roles with fresh conversation histories and a typed handoff. They may use the same configured model. Each pass allows up to six model turns and six source-tool calls per role. The investigator chooses when to search and fetch. The graph allows up to two passes.

The strict configuration uses investigator_v5 and verifier_v6. The investigator has search and clause-fetch tools and submits a packet of evidence IDs. The verifier receives the canonical excerpts and required provision list and has the source-check tool. It returns a verdict for every claim and can request more research. The coordinator enforces source integrity, coverage, and human-review flags. It can send the investigator back once with a query focused on missing or rejected provisions. The review brief shows each pass and its outcome.

Both roles submit through the typed `submit_result` output function, which is separate from the three source tools. Invalid schema output gets bounded correction feedback within the original six-turn limit. It cannot bypass required source work. Baseline prompts retain generated statements for the recorded comparison; the strict path intentionally uses canonical excerpts instead of paraphrases.

A successful search-and-audit pass can finish in four model calls. A second pass can take the total to eight or more. The live deployment's six-request cap remains in effect, so a retry can exhaust the hosted budget and use local fallback. The instructor showcase can demonstrate both passes without using provider quota.

An unsupported review can trigger one re-search; repeated failure escalates with claims discarded. Provider/schema errors use deterministic fallback and never count as successful hosted completion. Fallback runs preserve the failure reason and usage. All routes remain recommendations for an officer. These safeguards establish extractive fidelity and coverage, not broad language-model entailment accuracy.

## Verified evidence

On 2026-10-24 the previous v4/v5 configuration passed a live acceptance check in four provider requests. See `evaluations/hosted_postguard_smoke.json`. The current v5/v6 audit behavior is covered by simulated tests.

A prior live A/B comparison contains one complete baseline/strict pair, with the strict v3/v4 canonical-statement prompts. Raw quota-exhausted cells remain in `prompt_ab_quota_run.json`; incomplete cells and successful fallback are not counted as successful model output. That experiment predates the smaller v4/v5 selection protocol. Do not claim it compares the final prompt versions or provides statistical significance.

Earlier failures are retained in the hosted failure reports and incident log: semantic mistakes in the first live handoff, quota exhaustion, schema errors, long-quotation tool parsing errors and a provider function-name/channel parsing error. The latest pass does not erase those incidents. Scripted protocol tests cover allowlists, handoff, verifier coverage, bounded correction/re-search, invalid evidence, 429 behavior, retries and circuit state without consuming hosted quota.

## Local configuration

For a clean clone, follow the [Groq setup and live Docker commands](teammate_handoff.md#turn-on-live-groq-agents). Keep the key in the ignored `.env`. The free-plan flag records your confirmation.

```powershell
.\.venv\Scripts\python.exe src\live_acceptance.py --max-requests 6
```

The default API remains simulated even if hosted credentials exist. Optional standalone service use additionally requires `TRIAGE_ALLOW_HOSTED=true`, `TRIAGE_MODE=hosted` and the same configuration for API/worker. Compose deliberately excludes local credentials and does not enable hosted service calls by default.

Each HTTP request has a timeout and at most two transport/5xx attempts with backoff. Free token-limit headers pace later calls; a long reset stops the operation. HTTP 429 is not retried. Three failed client calls open its process-local circuit for 30 seconds; circuits are not shared between processes. Rate limits and model availability can change. Check the provider's own documentation before changing models or plans:

- [Groq tool support](https://console.groq.com/docs/tool-use/overview)
- [Rate limits](https://console.groq.com/docs/rate-limits)
- [Billing FAQ](https://console.groq.com/docs/billing-faqs)
- [OpenAI-compatible API](https://console.groq.com/docs/openai)

Provider token counts are attributed to each role/step when supplied. Unknown billed cost remains null. Simulation reports marked character-based token estimates and zero cost; cache hits clear current-run usage and count avoided simulated calls. Load and scaling experiments use simulation exclusively.
