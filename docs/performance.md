# Measured deployment performance — 2026-10-24

Measured on Windows with Docker Desktop Linux containers/WSL 2, 16 GB host RAM and approximately 7.6 GiB available to Docker. App dependencies include CPU Torch; the separate model service is simulated with real retrieval and a 0.15-second delay per model step. Three workers share the local durable queue and model service. No hosted model requests were made by the experiment.

`load/slo.json` declared the targets before measurement: 10 concurrent fictional attendance clients, 60 seconds, submission p95 <=750 ms, complete workflow p95 <=10 seconds, failures <=1%. Each round warms the path first. Locust ramps two users per second and drains in-flight work after the timed interval. Reported RPS uses Locust's measured runtime, including drain; counts include completed in-flight work. Completion latency includes submission, queueing, source work and polling observation, not only HTTP enqueue time.

| Workers | Cache | Completed | Workflow RPS | p50 ms | p95 ms | Submit p95 ms | Completion failures |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | disabled | 73 | 1.0898 | 9000 | 9200 | 110 | 0/73 |
| 3 | disabled | 131 | 2.0794 | 4200 | 6300 | 170 | 0/131 |
| 3 | 300-second TTL, warmed | 940 | 15.9147 | 440 | 850 | 560 | 0/940 |

All declared SLOs passed without changing the thresholds. Three workers achieved about 1.91 times the uncached throughput; scaling was not linear. The workload has repeated identical input, deliberately measuring a warm-cache case: 940 hits, zero misses after warmup, and 3,760 avoided simulated role calls. It is not a realistic cache-hit-rate estimate for a diverse petition population. Actual dollar savings are zero because simulation has zero billed cost. Hosted billed costs remain unknown outside this experiment.

The one-worker result is consistent with queueing behind a serial worker (completion median around nine seconds for ten clients). Three workers reduce queueing, while sharing CPU, source tooling, model-service concurrency and SQLite. Warm caching removes simulated generation/retrieval work, leaving API hashing, canonical revalidation, durable writes, polling and shared resource overhead. These are bottleneck inferences from the observed behavior, not isolated CPU/IO attribution. Submission p95 increases with the much higher cached request rate. Do not claim linear scalability or apply this SLO to cold fallback/hosted inference.

Authoritative data: `evaluations/load_report.json`, `load_w1_cache0_stats.csv`, `load_w3_cache0_stats.csv`, `load_w3_cache300_stats.csv`, their history/failure CSVs, and `load/locustfile.py`. The synthetic `WORKFLOW` row is the business metric; `CACHE` rows are accounting events, not additional network requests. Do not report the aggregate row as petition throughput.

Run from the project root after the ordinary three-worker deployment is healthy:

```powershell
.\.venv\Scripts\python.exe scripts/benchmark.py --seconds 60
```

Run separately from failure drivers or container regression tests. The driver temporarily disables the submission limit for measurement and restores the normal three-worker configuration afterwards. Routine authentication stays enabled. Controlled outage/circuit/429 results are recorded separately in `evaluations/deployed_failures.json`.
