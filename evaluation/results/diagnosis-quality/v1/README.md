# Diagnosis quality retest v1

This is the post-fix replay of the same 27 immutable real-v2 observation snapshots. The
predeclared plan binds commit `f6c4acb`, the unchanged v1 scoring rules, DeepSeek Flash with
thinking disabled and temperature zero, and all three model modes. The runner used commit
`2861a92`; each case records that revision plus source and input hashes. Evaluator labels were
joined only after all 81 outcomes existed.

## Results

| Mode | Fault Top-1/Top-3 | Safe controls | Failures | Gate passes | Model calls | Duration median / P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Single agent | 11/18, 11/18 | 9/9 | 1/27 | 6 | 53 | 4,625 / 5,219 ms |
| Controlled graph | 11/18, 11/18 | 8/9 | 3/27 | 5 | 74 | 4,781 / 11,266 ms |
| Controlled graph + simulated history | 11/18, 11/18 | 9/9 | 2/27 | 4 | 72 | 5,062 / 11,125 ms |

The earlier same-snapshot results were 8/18 Top-1, 0/9 controls and 4/27 failures for both
single-agent and controlled-graph, and 11/18, 0/9 and 4/27 for the later simulated-history
supplement. The post-fix run therefore demonstrates the intended control/failure routing change
and a descriptive Top-1 increase for the two no-history modes. Provider executions occurred at
different times, and simulated history was already an exploratory later batch, so these numbers
do not isolate every difference or establish production accuracy.

All nine single-agent controls and all nine simulated-history controls were safe. The controlled
graph missed one counter-evidence control only because its diagnosis response exceeded the schema
text limit; the other eight were safe. All nine insufficient-evidence cases now reach a bounded
model report instead of terminating at the first unavailable snapshot read. Every successful
normal, insufficient-evidence and counter-evidence control ended in `HUMAN_HANDOFF`, with no
candidate and no Gate pass.

The six retained failures were three extra-field/overlong-output schema failures, one additional
overlong-output failure, one incident-identity mismatch and one further extra-field plan failure.
They receive no diagnostic credit and were not retried. The exact cases and sanitized failure
events remain in the archive.

## Evidence and safety audit

There are 75 stored diagnosis reports and 150 declared Evidence references. All 150 resolve to
the same Incident and tenant, and all 150 Artifact blobs match their recorded content hashes.
Across the three modes, 15 candidates passed the deterministic Evidence Gate. Gate pass is only
evidence sufficiency; it is not treated as root-cause correctness. No approval decision, recovery
execution or write tool exists in this replay. The Policy, independent human approval and
deterministic execution/verifier chain are unchanged.

The three frozen memory-leak instances still produced no correct Top-1 in any mode: eight safe
handoffs and one invalid response. This replay improves false-positive handling but does not show
holdout memory-leak recall. The separate autonomous-v5 error had a retained-memory signal in its
actual TRACE context; a direct same-evidence replay and newly frozen generalization controls are
reported separately rather than inferred from this result.

## Resources and limitations

The run made 199 real provider calls. Total input/output tokens were 226,466/16,335 for single
agent, 381,006/23,880 for controlled graph, and 395,199/24,139 for simulated history. Actual
provider billing is unknown. Durations are runner wall time and include provider/tool/workflow
work; they are not human diagnosis time or production MTTR.

Simulated history remains explicitly fictional and is not evidence about confirmed historical
Incident memory. Real human approval time, labor, invoice reconciliation, real historical
retrieval and production incident data remain unmeasured.

Artifacts: [frozen plan](../../../real_protocol/v3/quality-retest-plan.json),
[score](run-001/score.json), [case audit](run-001/case-audit.json), and
[Evidence/call summary](run-001/audit-summary.json).
