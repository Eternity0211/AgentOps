# Frozen diagnosis error analysis

This report classifies the existing candidate 1.11 misses without rerunning or rescoring provider outputs.

## Census

- Fault outcomes: 54
- Top-1 correct: 36
- Top-1 errors: 18

## Root causes of misses

| Category | Count | Required response |
| --- | ---: | --- |
| `DOWNSTREAM_CAUSAL_SCOPE_NOT_EXPANDED` | 9 | Add bounded deterministic read-only downstream Evidence expansion after a failing dependency is observed; do not infer a cause or perform a write. |
| `EVIDENCE_CONSTRUCTION_GAP` | 9 | Adopt the already validated FC3 GC-aware context contract in the candidate path. |

All nine memory-leak misses safely handed off because the legacy context lacked the later FC3 GC-aware facts. All nine bad-configuration misses classified the observed HTTP symptom after collecting only gateway Evidence; no downstream configuration/deployment Evidence was available to distinguish the underlying cause.

## Decision

The candidate will combine the already validated GC-aware memory context with bounded deterministic downstream read-only expansion. It will not alter schemas, the Evidence Gate, model call ceilings, write authority, or recovery controls. Ranking changes are deferred until decisive Evidence exists.

## Limitations

- This is a deterministic post-hoc classification of frozen development outcomes, not a new quality measurement.
- Evaluator labels are used only after outcomes exist and are never passed to runtime or a model.
- The optimization decision must be tested on separate development data before the untouched FC4 holdout is opened.
