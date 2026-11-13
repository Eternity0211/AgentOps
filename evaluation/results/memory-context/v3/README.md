# Expanded memory-context paired result v3

The frozen ten-pair run completed all twenty newly invoked real-model outcomes without selective
reruns or reuse of v1/v2 outputs. Baseline correctness was 9/10 and candidate correctness was
10/10 (+1 case, +10 percentage points). Sustained-retention detection improved 1/2→2/2 (+1,
+50 percentage points within the two positives). Safe negatives remained 8/8→8/8, failures
remained 0→0, and every cited Evidence ID resolved to an observation owned by the same opaque case.
All predeclared acceptance checks passed.

Resource totals changed as follows: duration 20,549→20,689ms (+140), input tokens
26,865→25,198 (-1,667), output tokens 2,186→2,212 (+26), and rate-card upper bound
10,682,700→10,213,800 nUSD (-468,900). These are descriptive values. With only ten pairs and one
accuracy-discordant pair, the quality improvement is not a statistical-superiority claim.

The candidate improvement is bounded to these designed memory-evidence variants. FC3 closes the
memory mechanism and real transport work; broader untouched diagnosis quality remains FC4.
