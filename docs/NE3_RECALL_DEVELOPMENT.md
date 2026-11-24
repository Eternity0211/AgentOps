# NE3 recall development

## Scope

NE3 measures a deterministic evidence-readiness improvement on a new development-only
cohort. It does not reuse the opened confirmation-v2 labels, alter any of the 480 published
provider outcomes, or claim a model-diagnosis improvement. The baseline and candidate are
paired on the same eight cases; only the evidence bundle differs.

Four positive cases cover two decisive non-memory signals and two chronological memory
retention signals. Four negative controls cover a single source, stale evidence, unresolved
counter-evidence, and normal post-GC reclamation. Evaluator labels are stored separately and
are opened only by the scorer.

## Unchanged safety conditions

The readiness check preserves the Evidence Gate prerequisites: at least two independent
current sources, a 7,000-basis-point quality floor, no declared material missing evidence,
and no unresolved counter-evidence. Optional mechanism detail may remain unknown only after
the bounded candidate is otherwise supported. A memory-leak bundle additionally requires at
least five chronological samples, a before/after GC pair, positive net retention that persists
after GC, and an independent aligned impact source.

The scorer has no model or write path. It records every case, every failure reason, precision,
recall, negative-control safety, paired correctness with a 95% bootstrap interval, observation
counts, and zero model/write calls. Missing or invalid cases count as failures; there is no
selective rerun or exclusion.

## Acceptance criteria and test plan

Acceptance requires candidate recall and precision to improve without a negative-control false
positive, while retaining every failure and resource count. This is a development result and
cannot satisfy NE4 independent confirmation.

Tests validate strict schemas, label isolation, balanced positive/negative controls, unchanged
Gate preconditions, chronological-memory classification, hash-drift refusal, and the complete
score fields. Ruff, strict mypy, architecture checks, and the relevant unit suite must pass.
