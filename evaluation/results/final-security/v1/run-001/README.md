# Final adversarial and chaos comparison

| Metric | Baseline | Candidate | Absolute delta |
| --- | ---: | ---: | ---: |
| attack_block | 8/8 | 8/8 | +0.0% |
| safe_handoff | 4/4 | 4/4 | +0.0% |
| false_block | 0/1 | 0/1 | +0.0% |
| route_correctness | 13/13 | 13/13 | +0.0% |
| local JUnit duration | 829 ms | 10188 ms | +9359 ms |

Acceptance: `PASS`. Provider cost is 0 in both arms because these deterministic cases dispatch no provider request.

This is a fixed local safety census, not model quality, attack prevalence, or production reliability evidence.
