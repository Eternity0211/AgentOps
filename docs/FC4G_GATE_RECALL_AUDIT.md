# FC4g evidence-gate recall audit

## Scope and immutable inputs

This is a post-confirmation error analysis of the published FC4f4 run, not a new
confirmation or a rescore. It reads the 120 fault labels from
`evaluation/lab_holdout/v2/evaluator_only/labels.json`, the controlled-graph
outcomes and the corresponding validated diagnosis reports under
`evaluation/results/confirmation-v2/run-001/`. The frozen scorer and all 480
provider outcomes remain unchanged.

The predeclared gate-recall numerator is a fault with both the correct Top-1
candidate and an Evidence Gate pass. Its denominator is all 120 fault cases.

| Funnel stage | Cases | Fraction of 120 |
| --- | ---: | ---: |
| Fault cases | 120 | 100% |
| Correct Top-1 candidate | 47 | 39.17% |
| Correct Top-1 and Gate pass | 16 | 13.33% |
| Correct Top-1 but Gate did not pass | 31 | 25.83% |
| No candidate | 72 | 60.00% |
| Wrong Top-1 candidate | 1 | 0.83% |
| Wrong candidate with Gate pass | 0 | 0% |

All 31 correct-but-not-passed reports declare at least one missing item in the
candidate. Under the unchanged Gate contract, a declared requirement fails
closed. The archived run contains only the boolean Gate outcome, not the full
decision reason codes, so the missing declarations cannot be asserted as the
*only* reason for any particular rejection. This audit does not infer that the
missing items were optional. Several examples require genuinely decisive
telemetry, such as downstream spans or database-side saturation metrics.

The 20 memory-leak labeled cases all produced no candidate. The generated
snapshots expose a retained-heap value and warning but no chronological
post-GC growth series or matching elevated checkout error/latency metrics in
the local record. Refusing a leak conclusion on those observations is a safe
outcome. The evaluator-only labels remain fixed; changing them after seeing
results would invalidate the confirmation. A new, disjoint development cohort
must add a reproducible retention trend, cross-source corroboration, aligned
impact metrics and paired negative controls before a memory-leak recall claim.

## Optimization decision

1. Preserve the Gate rules, including missing-evidence refusal, independent
   sources, freshness, Artifact binding and counter-evidence resolution.
2. On development data, improve acquisition of decisive missing telemetry and
   distinguish material missing facts from deeper optional mechanism details.
   Uncertainty may describe optional unknowns only if the bounded candidate is
   already supported; material gaps remain in `missing_evidence`.
3. Archive full Gate reason codes in future evaluation runs, without adding
   labels to runtime or model context, to separate reference, quality,
   independence, counter-evidence and completeness failures.
4. Freeze a new disjoint confirmation cohort and paired protocol before any
   provider confirmation. Report Gate precision, recall, Top-1, safe controls,
   fabricated references, latency and cost. No selective reruns or reuse of
   opened FC4f4 labels for confirmation.

## Safety recheck

The focused Evidence Gate, Ground Truth, telemetry, adversarial, approval,
execution and health-verification unit selection completed with **240 passed**
on 2026-11-24 (`pytest -q -o addopts=''` with the selected test modules).
The default full-project coverage requirement is 100%, so a focused subset
run must disable only that global coverage gate; a first focused invocation
passed all 240 tests but exited nonzero because it measured 36.30% of the
entire source tree. The last full-project verification remains 3,268 passed,
2 skipped and 100% coverage on 2026-11-23. The focused recheck is a regression
check, not an empirical unsafe-action or recovery-rate measurement.
