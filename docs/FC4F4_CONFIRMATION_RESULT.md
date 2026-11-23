# FC4f4 disjoint lab confirmation

The [frozen protocol](../evaluation/confirmation_v2/plan.json) ran once on 160 synthetic
observation snapshots that do not reuse the earlier holdout or development IDs and input hashes.
It retained all 480 outcomes, with rules, single model and controlled graph interleaved by dataset
index. Both model arms used DeepSeek Flash, transport 1.12, the same evidence strategy and the
same 6 physical/4 logical model and 12 read ceilings. Evaluator labels were loaded only after
all outcome and runtime bindings validated. The [full paired score and audit](../evaluation/results/confirmation-v2/run-001/analysis/score.json)
remain the numerical authority.

| Measure | Single model | Controlled graph | Candidate minus baseline | Paired 95% interval |
| --- | ---: | ---: | ---: | ---: |
| Top-1 correct faults | 14/120 (11.67%) | 47/120 (39.17%) | +33; +27.5 points | +18.33 to +36.67 points |
| Top-3 correct faults | 14/120 (11.67%) | 47/120 (39.17%) | +33; +27.5 points | +18.33 to +36.67 points |
| Gate recall on faults | 1/120 (0.83%) | 16/120 (13.33%) | +15; +12.5 points | +6.67 to +18.33 points |
| Safe controls | 40/40 | 40/40 | 0 | 0 to 0 |
| Valid outcomes | 160/160 | 160/160 | 0 | 0 to 0 |
| Workflow duration median | 4,430 ms | 5,031.5 ms | +601.5 ms | +328.5 to +1,132.5 ms |
| Workflow duration P95 | 5,969 ms | 11,765 ms | +5,796 ms | +5,218 to +6,438 ms |
| Input tokens median | 4,260.5 | 4,475 | +214.5 | +106.5 to +593 |
| Rate-card upper bound median | 1,940,400 nUSD | 2,129,250 nUSD | +188,850 nUSD | +106,950 to +491,415 nUSD |
| Rate-card upper bound P95 | 2,526,600 nUSD | 5,514,600 nUSD | +2,988,000 nUSD | +2,384,620 to +3,195,000 nUSD |

The frozen paired scorer marks Top-1 and Top-3 `IMPROVED`; Top-1 exceeds the 15-point minimum
effect, with Holm-adjusted p approximately 9.23e-7. The critical-safety and median latency/cost
ceiling gates pass. No model outcome failed. Graph citations resolve and match the same Incident's
immutable Artifact in 239/239 references; single model does so in 64/64. Neither model arm has a
terminal schema/protocol invalid or fabricated reference. Rules are a secondary reference:
0/120 Top-1, 30/40 safe controls and 10/160 failed outcomes under its fixed twelve-read schedule.

The resource metrics themselves regress. The graph's median duration is 13.58% higher and its
rate-card estimate is 9.73% higher; P95 duration and cost are much higher. Passing the frozen
ceilings means this tradeoff was accepted for the lab quality claim, not that resources improved.
The graph's 47/120 Top-1 leaves substantial quality headroom. This result measures correctness
on synthetic snapshots, not actual time to correct diagnosis, operator labor, approved recovery,
MTTR, recurrence or billed cost. Those remain separate metrics with explicit external prerequisites.

The older FC4d 480 outcomes and FC4f2b 54 development outcomes were not rerun or substituted into
this comparison. All raw results, call audits, Evidence/Artifacts and the scorer output are retained
in the [new run archive](../evaluation/results/confirmation-v2/run-001).
Its 6,035 raw and analysis files are bound by a SHA-256 manifest with digest
`b2591cd04f8f3ecae3f2d7fdd1e84d4b81db833f156ca776dff97eca9089206c`.
