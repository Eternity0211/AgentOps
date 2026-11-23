# FC4f2b fallback development comparison

The frozen [protocol](../evaluation/final_diagnosis_optimization/v2/pair-plan.json) paired
transport 1.11 and 1.12 on the same 27 development snapshots, in alternating order. The only
intended code difference is the deterministic, candidate-free human handoff after a second
repairable DIAGNOSE validation failure. Both arms used DeepSeek Flash with the same settings,
GC-aware causal-scope strategy, graph, Evidence Gate and 6/4/12 call ceilings. This dataset was
previously used for evidence-strategy development; it is not untouched confirmation evidence.

All 54 outcomes are present. The frozen [score and decision](../evaluation/results/final-diagnosis-optimization/v2/run-001/analysis/decision.json)
find zero failed outcomes in either arm, 9/9 safe controls in each arm, and complete same-Incident
Evidence/Artifact resolution: 78/78 baseline citations and 53/53 candidate citations. Candidate
terminal schema invalids are zero. The predeclared safety and median/P95 resource ceilings pass.

| Metric | Baseline 1.11 | Candidate 1.12 | Delta | Paired 95% median-delta interval |
| --- | ---: | ---: | ---: | ---: |
| Workflow duration median | 9,625 ms | 5,907 ms | -3,718 ms | [-5,250, +766] ms |
| Workflow duration P95 | 14,391 ms | 11,735 ms | -2,656 ms | See full paired score |
| Input tokens median | 9,860 | 4,901 | -4,959 | [-6,538, +161] |
| Input tokens P95 | 13,437 | 13,154 | -283 | See full paired score |
| Output tokens median | 1,451 | 857 | -594 | [-837, +27] |
| Rate-card upper bound median | 4,699,200 nUSD | 2,495,100 nUSD | -2,204,100 nUSD | [-2,979,000, -4,200] nUSD |
| Rate-card upper bound P95 | 6,072,000 nUSD | 5,993,400 nUSD | -78,600 nUSD | See full paired score |

The [post-run exploratory quality audit](../evaluation/results/final-diagnosis-optimization/v2/run-001/analysis/quality-audit.json)
records Top-1 and Top-3 as 15/18 to 12/18, a -3-case or -16.67-point difference. Their paired
95% interval is -38.89 to +5.56 points, so the result does not establish a quality improvement
or regression. Neither arm emitted a terminal-fallback event. Baseline made 85 Provider calls and
candidate 78, reflecting different observed plan/replan paths. The resource differences cannot be
attributed to the fallback, and the FC1 score marks every resource metric
`NO_PROVEN_IMPROVEMENT` after its paired tests and multiple-comparison correction. The rate-card
figure is not actual billing; no human labor, approved recovery or MTTR was measured.

The narrow frozen development gate passed. It verifies that the candidate can complete this set
without failure or resource ceiling breach; the deterministic bounded-replan fixture covers the
fallback path that the live calls did not activate. The project-level effect remains unproven.
The next step is a new disjoint, label-isolated cohort frozen before its first Provider call, then
one complete rules/single/graph confirmation. The 480 earlier FC4d results are immutable and
cannot be reused as a candidate arm.

Raw outcomes, call audits, Evidence/Artifacts, the [paired score](../evaluation/results/final-diagnosis-optimization/v2/run-001/analysis/score.json),
and all 1,206 file hashes are retained under
[`evaluation/results/final-diagnosis-optimization/v2/run-001`](../evaluation/results/final-diagnosis-optimization/v2/run-001).
The manifest SHA-256 is
`69e80279bd41499d88366aae7bbfa5b719ebb9b91ffaa7eec157bfb157978227`.
Publication tests recompute the score, decision, quality audit and every archived file hash.
A direct Git-object audit of this exact manifest also verified 1,206/1,206 files with no mismatch.
The repository-wide Git-object audit now recognizes both flat and versioned manifest formats, but
still reports 891 mismatches in four older archives. Those pre-existing records remain visible and
are not repaired by rescoring or rewriting this run.
