# Final durability paired comparison

| Case | Control route | Treatment route | Total latency control→treatment (delta ms) | Duplicate effects | Ambiguous redispatches | Lost Evidence |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `before-dispatch` | `COMPLETED` | `SAFE_REPLAY_NO_DISPATCH` | 203→106 (-97) | 0 | 0 | 0 |
| `after-dispatch-unknown` | `COMPLETED` | `NEEDS_HUMAN_NO_REDISPATCH` | 80→48 (-32) | 0 | 0 | 0 |
| `after-persisted-result` | `COMPLETED` | `RESUMED_COMPLETION` | 89→111 (+22) | 0 | 0 | 0 |
| `partial-parallel-reads` | `COMPLETED` | `RESUMED_COMPLETION` | 75→119 (+44) | 0 | 0 | 0 |
| `checkpoint-replacement` | `COMPLETED` | `RESUMED_COMPLETION` | 106→119 (+13) | 0 | 0 | 0 |
| `stale-lease` | `COMPLETED` | `RESUMED_COMPLETION` | 92→149 (+57) | 0 | 0 | 0 |
| `bounded-timeout` | `COMPLETED` | `SAFE_HANDOFF` | 83→69 (-14) | 0 | 0 | 0 |
| `duplicate-delivery` | `COMPLETED` | `RESUMED_COMPLETION` | 78→91 (+13) | 0 | 0 | 0 |

Acceptance: `PASS`; route matches 8/8, duplicate effects 0, ambiguous redispatches 0.

Latency is local monotonic elapsed time. Token and rate-card fields are descriptive; the latter is not actual provider billing. Controlled substitutes do not establish real-provider quality, human labor savings, MTTR, or production reliability.
