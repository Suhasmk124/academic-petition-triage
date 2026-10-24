# Safety, feedback and review recovery

Implemented on 2026-10-24. This is the next local-service stage, not completion of the entire course brief.

## Safeguards

`src/safety.py` applies versioned `rules-v1` checks for explicit instruction overrides, role spoofing, secret requests, command execution requests, verification bypasses and a small English abuse lexicon. NFKC normalization and removal of Unicode format characters cover selected simple obfuscations. The API returns 403 with `CONTENT_REQUIRES_REVIEW`, quarantines the bounded request and starts no job. The response contains rule codes and a reference, not an echo of the petition. Direct workflow/hosted entry points and workers also check input before doing work. Reviewed tool quotations are screened before forwarding to the agent.

The worker applies an independent final gate to both local execution modes. It checks routing/human-decision flags, exact canonical quotations and citation metadata, complete pilot provision sets and explanatory text. Canonical clauses are reconstructed from the reviewed source anchors, rather than trusting returned citation labels. Unsupported or malformed output is withheld and replaced by an empty `ESCALATE` brief. A successfully withheld output has job status `SUCCEEDED` and triage status `ESCALATE`; these describe different things. The service retains typed agent counters/timings but strips raw petitions, arbitrary fields, model payloads and diagnostics from newly produced results. Stored older runs are not rewritten.

These checks are intentionally limited. Patterns can miss paraphrased, encoded, multilingual and new attacks, and may flag benign quoted instructions or insults. The output gate is extractive and is enabled at the local worker boundary; hosted CLI results still use the existing fallible semantic verifier and narrow guards. The canonical check uses the local extracted source and reviewed anchors, not independent re-reading of the PDF. Source matching does not prove eligibility or semantic entailment. The 22-case rule set is a post-implementation regression set, not a held-out security benchmark. No broad security certification or complete L4 claim is made.

The portal now sends a restrictive same-origin Content Security Policy, anti-framing and MIME-sniffing headers, and a no-referrer policy. API documentation is kept separate because its generated UI uses inline scripts. Rendering continues to use DOM text nodes. There is still no authentication or user separation; use loopback and fictional data only.

## Feedback and quality sampling

- `PUT /runs/{run_id}/feedback`: save/update one entry for a completed run. Fields: `rating` (`helpful` or `needs_review`), `category` (`none`, `missing_rule`, `incorrect_citation`, `unclear`, `other`), optional `comment` up to 500 characters, and strict `synthetic: true`. Values are validated and policy-checked before storage. Pending runs return 409, unknown runs 404. Repeated saves update the same row rather than adding duplicates.
- `GET /runs/{run_id}/feedback`: retrieve saved feedback, or `feedback: null` for an existing run without feedback.
- `GET /quality-samples?limit=20`: prioritize failed jobs, escalations, blocked outputs and negative feedback, then a stable SHA-256-based 10% sample of other completed runs. Limit is 1–100. Returns metadata only, without petition bodies, source text or feedback comments. Sampling scans the local completed-job table; it is a prototype for small local datasets, not a large-scale sampling system. A response may truncate the priority set to the requested limit.

Feedback persists in a new SQLite table created by the existing idempotent initialization. No previous jobs or tables are deleted. Feedback never changes an academic recommendation and does not automatically tune a prompt or model. There is no feedback authorization beyond the current local-only deployment.

## Useful interface additions

Each expanded citation links to `/handbook#page=N` for the actual local source PDF. The API supports byte-range PDF requests through FileResponse. PDF viewer page-fragment handling depends on the browser. After submission the URL includes the run UUID, allowing refresh/bookmark recovery. A separate form reopens a run by ID. Petition text is not put in URLs, localStorage or sessionStorage; a browser may still retain its own form history. Saved feedback is restored with the brief.

## Verification

Run from the project root using the existing environment:

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
.\.venv\Scripts\python.exe src\check_project.py --service --evaluation
```

The regression suite covers API rejection without queueing, direct-entry rejection, poisoned tool text, eleven output mutations, malformed output, metric filtering, worker boundaries, feedback validation/update/persistence, queue-state restrictions, sampling and PDF/security headers. All 48 fixed workflow cases also pass through the new final output gate. The real HTTP smoke checks blocked input, source-checked results, feedback, quality sampling, PDF delivery and persistence after API restart. No hosted calls are needed. Reports remain under `evaluations/`; browser verification is recorded separately.

The final combined run passed 76 tests, 22 safety-rule scenarios, 11 focused retrieval checks, four deterministic smoke cases, 48 fixed workflow runs and the extended HTTP/worker integration check. Browser checks passed for rejection/recovery, saving/restoring feedback, reopening by bookmark or UUID, preserving the existing brief after an unknown ID, and mobile overflow. See `evaluations/browser_safety_feedback.json`. These results do not establish hosted semantic accuracy or complete security protection.

## Remaining work

This stage advances L4 and implements the local L6 feedback/sampling path. Broad security evaluation, held-out semantic evaluation, hosted prompt A/B, authenticated access, distributed queue hardening, OpenTelemetry/Prometheus/Grafana, Docker Compose with at least four services, a separate stub service, worker scaling and declared-SLO/Locust measurements remain open. Docker CLI was not available in this environment at inspection; no untested container deployment is claimed. See `docs/runbook.md` and the recorded semantic-verification incident for current operational guidance.
