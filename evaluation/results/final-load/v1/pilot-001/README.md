# PostgreSQL capacity pilot

| Workers | Repetitions | Median jobs/s | Delta vs 1 worker | Queue P95 ms | Workflow P95 ms | Errors | Duplicate ownership |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3 | 16.473 | +0.0% | 3202 | 3221 | 0 | 0 |
| 2 | 3 | 29.223 | +77.4% | 1853 | 1874 | 0 | 0 |
| 4 | 3 | 30.331 | +84.1% | 1787 | 1832 | 0 | 0 |
| 8 | 3 | 24.051 | +46.0% | 2211 | 2311 | 0 | 0 |

The frozen variance rule selected 11 repetitions per worker level for the confirmatory run.

This pilot is sizing evidence only. Local process CPU and Python heap exclude the database/container. It is not production capacity, availability, or a broker decision.
