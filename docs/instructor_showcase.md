# Instructor showcase

The showcase runs on loopback and uses local simulated inference. Its database, Grafana, and monitoring history are separate from the live workspace. Use fictional petition text and specimen attachments.

## Start the showcase

Open Docker Desktop. From the repository root in PowerShell, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1 -Showcase
```

Open the [petition desk](http://127.0.0.1:8003). Use the role picker to sign in as `student`, `reviewer`, or `admin`. All three use `pass@1234`. Sign out to switch roles.

1. As **Student**, submit a fictional attendance petition with a specimen attachment and confirm the fictional-data checkbox. Open the linked handbook paragraphs and **Agent activity**. The investigator searches the handbook and hands off a source packet. The source auditor checks the quotations and whether the packet covers every required provision.
2. As **Reviewer**, open the case from the review queue and save a recommendation or request for evidence. Switch back to **Student** to show that the review appears on their own case.
3. As **Administrator**, open the staff queue to show workspace-wide access.

To show the auditor sending work back, run this from the repository root while the showcase is up:

```powershell
docker compose -f compose.yaml -f compose.showcase.yaml exec -T stub python -m stub_model --demo-audit-retry
```

This command deliberately omits two attendance provisions on pass one. The retained quote matches its source, but the auditor returns the incomplete packet. Pass two retrieves the missing clauses and clears the packet for officer review. This demonstration uses the real handbook tools and a simulated model, with zero hosted requests.

## Show the system under load

1. Open [Grafana](http://127.0.0.1:3001/d/petition-triage) with username `admin` and password `pass@1234`. Leave the dashboard open with auto-refresh on and the range set to **Last 5 minutes**.
2. In a second PowerShell window at the repository root, run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\showcase_load.ps1 -Users 10 -Seconds 60
   ```

3. On Grafana, follow active workers, queue depth, completed workflows per second, failure count, and workflow p95. Submission HTTP p95 measures the time to acknowledge the request. Workflow p95 includes queueing and worker execution. The Locust console reports separate HTTP and complete-workflow results and checks that cases finish with citations and a human-review recommendation.
4. Open [Prometheus targets](http://127.0.0.1:9091/targets) and show the petition API target is **UP**. Copy the **Trace reference** from a completed case, then open `http://127.0.0.1:16687/trace/<trace-reference>`. Expand the request, worker, investigator, verifier, and source-tool spans.

On the verification run, 10 simulated users submitted 169 workflows over 60 seconds with three workers and zero failures. Locust reported a 4.4 s workflow p95 and a 180 ms submission p95. Performance varies by machine.

The showcase starts three workers and disables the case-result cache so each submitted load case exercises the workflow. To compare different worker counts, change the scale, wait for the active-worker panel to settle, and rerun the same test:

```powershell
docker compose -f compose.yaml -f compose.showcase.yaml up -d --no-build --scale worker=1 worker
docker compose -f compose.yaml -f compose.showcase.yaml up -d --no-build --scale worker=3 worker
```

Run each configuration separately and compare its Locust `WORKFLOW` row. Monitor the queue as slower runs continue to drain.

## Stop

```powershell
docker compose -f compose.yaml -f compose.showcase.yaml stop
```
