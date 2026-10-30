# AgentOps bounded local load evaluation

- Run: `bounded-load-20261030-001`
- Code revision: `1678dd05e077dcf16db7dd7779f2642009275406`
- Plan: `phase12-bounded-load-v1` (`778e86e3b97c774233e9675ee4f8b104bd7ac14ec7f907b71cff5da1b1168c3c`)
- Environment: Python 3.12.14 on `win32-amd64`; machine=AMD64;logical_cpu_count=8
- Window: 2026-10-30T01:35:33.060649Z to 2026-10-30T01:35:51.057636Z
- Collected tests: 4

| Workload | Completed | Concurrency | Duration ms | Observed ops/s |
| --- | ---: | ---: | ---: | ---: |
| `api-health` | 128/128 | 8 | 247 | 518.218 |
| `evidence-query` | 64/64 | 8 | 7892 | 8.109 |
| `job-leasing` | 64/64 | 8 | 1968 | 32.520 |
| `worker-processing` | 64/64 | 4 | 5 | 12800.000 |

> These are bounded component-level measurements from one local run. PostgreSQL workloads use a temporary Testcontainer; API and worker workloads run in-process. The figures are not production throughput, capacity, availability, or reliability claims and do not justify adding a message broker.
