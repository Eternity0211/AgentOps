# AgentOps bounded local load evaluation

- Run: `deepseek-load-001`
- Code revision: `44073d27c83faab5ba0c473cef326008f3ca6316`
- Plan: `phase12-bounded-load-v1` (`778e86e3b97c774233e9675ee4f8b104bd7ac14ec7f907b71cff5da1b1168c3c`)
- Environment: Python 3.12.14 on `win32-amd64`; machine=AMD64;logical_cpu_count=8
- Window: 2026-11-03T03:05:46.517467Z to 2026-11-03T03:06:14.307592Z
- Collected tests: 4

| Workload | Completed | Concurrency | Duration ms | Observed ops/s |
| --- | ---: | ---: | ---: | ---: |
| `api-health` | 128/128 | 8 | 352 | 363.636 |
| `evidence-query` | 64/64 | 8 | 12605 | 5.077 |
| `job-leasing` | 64/64 | 8 | 2575 | 24.854 |
| `worker-processing` | 64/64 | 4 | 10 | 6400.000 |

> These are bounded component-level measurements from one local run. PostgreSQL workloads use a temporary Testcontainer; API and worker workloads run in-process. The figures are not production throughput, capacity, availability, or reliability claims and do not justify adding a message broker.
