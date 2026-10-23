# Structured evidence assessment — 2026-10-23

The workflow now hands a structured assessment from investigation to verification. It classifies three narrow pilot types: attendance, medical terminal-exam absence, and X-grade queries. Other types escalate. Classification is a keyword heuristic and is not a general petition classifier.

An assessment contains extractive rule findings, exact quotes, source citations, missing provisions, supporting records still requiring review, a routing recommendation and reasons. Petition statements are never treated as verified medical/attendance records. The listed missing evidence is a review checklist, not a claim that the petition omitted every item.

Each finding is checked against its canonical indexed record: evidence ID, full citation metadata, page offsets/hash, quote presence and statement equality to the quoted rule. Altered statements and fabricated locations fail verification. One focused re-search is allowed; a second failure escalates and discards unverified findings. This is verification of extractive source matches, not semantic entailment of generated prose.

All three route names are represented in the output contract, but this pilot emits only REFER_TO_COMMITTEE (human officer/committee referral). GRANT_UNDER_PROVISION and REJECT_UNDER_PROVISION are not implemented eligibility behaviors. No final academic decision is made. Even REVIEW_REQUIRED means the rules were source-verified, not that eligibility was established.

The public run_petition entry point validates nonblank text and length before invoking LangGraph. There is no API or quarantine yet; D1 as a whole is incomplete. The graph remains deterministic Python nodes, not two independent LLM agents. Model/provider selection and semantic claim checking remain future work.

Run all implemented regression checks once after a set of changes:

```powershell
& '.\.venv\Scripts\python.exe' '.\src\check_project.py'
```

This includes source-backed unit tests, retrieval checks and real workflow cases, sharing the retrieval model within the process. Reports are written to evaluations/. The focused checks do not replace the course's fixed 20+ quality scenarios, prompt comparisons or operational evaluation.
