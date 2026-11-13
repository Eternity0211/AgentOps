# PostgreSQL capacity confirmatory comparison

| Workers | Repetitions | Median jobs/s (95% interval) | Delta vs 1 worker | Queue P95 ms | Workflow P95 ms | Errors | Duplicates |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 11 | 17.227 [14.509, 17.782] | +0.0% | 3297 | 3318 | 0 | 0 |
| 2 | 11 | 28.946 [27.984, 29.574] | +72.5% | 1858 | 1882 | 0 | 0 |
| 4 | 11 | 28.959 [26.688, 29.384] | +75.6% | 1866 | 1912 | 0 | 0 |
| 8 | 11 | 21.011 [18.561, 22.503] | +32.0% | 2608 | 2692 | 0 | 0 |

Broker decision: `BROKER_EVALUATION_REQUIRED`. The measured 8/4 throughput ratio was 0.726; queue-wait P95 ratio was 1.398.

These are bounded local results. Process CPU and Python heap exclude PostgreSQL and container resources; no production capacity or availability claim is made.
