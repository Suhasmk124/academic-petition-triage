# Hosted roles and free-tier development

The default Compose service uses a simulated model with real retrieval/source tools. It makes zero hosted calls. Hosted use requires explicit local opt-in and credentials; no paid fallback or automatic model/provider switch exists.

## Current protocol

LangGraph runs separately prompted investigator and verifier roles with fresh conversation histories and a typed handoff. They may use the same configured model. Each has six model turns and six source-tool calls; at most two investigation/verification passes are allowed. Retrieval is chosen by the investigator rather than a hidden pre-search. Both roles can select search, exact-clause fetch or bounded quote checking.

The strict configuration uses investigator_v4 and verifier_v5. The investigator selects one evidence ID per required provision. The server constructs complete canonical source excerpts; it does not let the model invent citation locations or alter quotations. The verifier independently calls the quote-check tool and supplies a decision for every claim. Complete required-provision coverage, exact statement identity, source integrity and human-review flags are enforced outside the model. Standard verdict labels are server-generated audit text, not model-written semantic explanations.

Both roles submit through the typed `submit_result` output function, which is separate from the three source tools. Invalid schema output gets bounded correction feedback within the original six-turn limit. It cannot bypass required source work. Baseline prompts retain generated statements for the recorded comparison; the strict path intentionally uses canonical excerpts instead of paraphrases.

An unsupported review can trigger one re-search; repeated failure escalates with claims discarded. Provider/schema errors use deterministic fallback and never count as successful hosted completion. Fallback runs preserve the failure reason and usage. All routes remain recommendations for an officer. These safeguards establish extractive fidelity and coverage, not broad language-model entailment accuracy.

## Verified evidence

On 2026-10-24 the final strict live acceptance passed in four provider requests: investigator selected search and submitted three source IDs; verifier selected quote checking and submitted three decisions. Both role metrics report success, and the final source gate passed. See `evaluations/hosted_postguard_smoke.json`. This is one fictional public-handbook case, not a broad accuracy claim.

A prior live A/B comparison contains one complete baseline/strict pair, with the strict v3/v4 canonical-statement prompts. Raw quota-exhausted cells remain in `prompt_ab_quota_run.json`; incomplete cells and successful fallback are not counted as successful model output. That experiment predates the smaller v4/v5 selection protocol. Do not claim it compares the final prompt versions or provides statistical significance.

Earlier failures are retained in the hosted failure reports and incident log: semantic mistakes in the first live handoff, quota exhaustion, schema errors, long-quotation tool parsing errors and a provider function-name/channel parsing error. The latest pass does not erase those incidents. Scripted protocol tests cover allowlists, handoff, verifier coverage, bounded correction/re-search, invalid evidence, 429 behavior, retries and circuit state without consuming hosted quota.

## Local configuration

Use the ignored `.env` and the blank tracked `.env.example`. Set `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, and assert `LLM_FREE_PLAN_CONFIRMED=true` only after checking your account is on the Free Plan. Do not upgrade or add payment for this project. The flag is your assertion, not an automatic billing check. Never paste keys into chat, logs or Git.

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
