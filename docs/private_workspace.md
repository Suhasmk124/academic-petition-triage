# Live agents and private supporting documents

Follow the [Groq key and configuration steps](teammate_handoff.md#turn-on-live-groq-agents). On Windows, with Docker Desktop running and your hosted provider settings in the ignored local `.env`:

```powershell
.\scripts\start.ps1 -Live
```

Open http://127.0.0.1:8002 and use the separate workspace key in .secrets/private_triage_key. This starts an isolated Compose project (academic-petition-private), with its own database, one worker, and no public monitoring ports. The original demo remains separate and uses the original startup command.

Type the petition and optionally select one PDF, PNG or JPEG (5 MiB maximum). The file is stored atomically with the run, can be downloaded or removed in the review brief, and is never opened, parsed, verified or sent to the provider. The original petition is available to the local reviewer; neither it nor the document is included in the audit export. Downloads use a generic filename and are served as attachments. Upload checks cover size and file signature, not malware scanning or authenticity. Remove attachment deletes the application record; it is not secure erasure from disk/backups.

For private runs, the app classifies the text locally. Only a fixed handbook question selected by category and public handbook evidence are used in the hosted agent workflow. Personal details, user-entered facts and file data stay local. The local worker applies the final citation gate and conditional recommendation to the actual petition. Unsupported categories go straight to local review. The result distinguishes hosted output from deterministic fallback, with at most six hosted request attempts per run. Provider errors or quota exhaustion may lead to fallback; the app does not switch to a paid provider.

Use this only as a restricted local workspace. The original workspace key is now the administrator credential. Students can only open cases they submitted under their own account; reviewers see the private queue. Records are stored in a local Docker volume, without application-level encryption. Keep the workspace key and host access private. An officer still verifies evidence and makes all decisions.

Stop the private workspace without removing stored records:

```powershell
docker compose -p academic-petition-private -f compose.yaml -f compose.private.yaml stop
```

Verification: 108 local tests passed. One end-to-end smoke run with no personal data used four hosted requests, completed both agent roles, passed the source gate, and verified authenticated download, exclusion from exports, and removal. To repeat deliberately, run scripts/verify_private.py with the project Python environment while the private workspace is running; it consumes hosted quota.

The review brief shows the investigator’s selected clauses and the verifier’s per-clause support verdicts after the local source gate passes. This is separate from the local recommendation about the submitted facts. A recoverable provider tool-format rejection after the required source tool gets one plain-JSON repair attempt within the same request budget; transient transport/server retries also count toward that budget. Rate limits and other non-recoverable provider errors stop rather than spending further quota. Fallback details use fixed messages and may show the role and HTTP status, never raw provider diagnostics. Older runs lack these new fields and need a new submission to obtain them.


## Student, reviewer and administrator walkthrough

1. Open http://127.0.0.1:8002, sign in as **admin** using the original private workspace key, and create one Student and one Reviewer account. Use distinct passwords of at least 12 characters.
2. Sign out and sign in as the student. Submit a test petition with an optional supporting document. **My petitions** lists only that student's cases.
3. In the brief, read **What this means for your petition**. The app composes this plain-language answer locally from the submitted attendance figure and the supported handbook clauses. Each section link expands the exact quotation; the PDF link opens the page in the full handbook. This is a single petition response, not a multi-turn chat.
4. Show **Agent activity**: completed tool actions, role durations, the local source gate and human review status. Successful hosted runs also show per-clause verifier support. These are recorded actions, not hidden model reasoning or a streaming trace.
5. Sign in as the reviewer. Open the **Officer review queue**, inspect the brief and attachment, then record an officer recommendation or request for information. Reviewers cannot submit as students or remove their files. The student can reopen the case to see the reviewer name, outcome and note. No action here is a final institutional decision.
6. Older cases created before accounts were introduced remain visible to staff; they have no student owner. Submit a new case as a student to test ownership.

This is local account and role management, not institutional single sign-on. The administrator credential can access every case. Keep it private.
