# Memory-context paired result v1

The frozen five-pair run completed all ten real-model outcomes without selective reruns. Baseline
correctness was 3/5 and candidate correctness was 4/5 (+1, +20 percentage points). Sustained
retention detection improved 0/1→1/1. The frozen lexical scorer reported safe negatives 3/4→3/4,
so predeclared acceptance failed.

Review shows the candidate's counted false positive explicitly said the pattern was “normal warmup,
not a leak”; the frozen scorer matched the phrase “memory retention” without accounting for
negation. This is a scorer defect, not permission to relabel the frozen result. The failed score is
retained, and a revised scorer requires a newly frozen, fully rerun comparison.

Resource totals changed as follows: duration 10,890→10,406ms (-484), input tokens
12,632→11,863 (-769), output tokens 991→1,065 (+74), and rate-card upper bound
4,978,800→4,836,900 nUSD (-141,900). With only five pairs and a failed acceptance gate, these are
descriptive values, not efficiency claims. Actual billing remains unknown.
