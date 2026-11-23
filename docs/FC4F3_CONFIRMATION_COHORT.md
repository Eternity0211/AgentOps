# FC4f3 confirmation cohort freeze

The new [160-case input cohort](../evaluation/datasets/lab-holdout-v2/index.json) was generated
from the versioned [plan](../evaluation/lab_holdout/v2/plan.json) before any candidate Provider
call. It contains 20 parameterized cases for each of six fault families, plus 10 each of normal,
insufficient-evidence, counter-evidence, and prompt-injection controls. The 120 fault pairs exceed
the predeclared 103-pair minimum for a 15-point Top-1 effect under the plan's assumed 30% discordant
pair rate, two-sided 5% alpha, and 80% power. This sizing calculation is conditional on those
assumptions; it does not guarantee the observed effect or significance.

The [generator](../evaluation/freeze_lab_holdout_v2.py) uses a new identity namespace, different
observation dates, and a distinct parameter range and provenance version. Its exact generated IDs
and input hashes have zero overlap with the earlier 160-case lab holdout and the 27-case development
set. The inputs contain no expected labels. The separate evaluator-only directory holds labels,
power calculation and a [file-hash manifest](../evaluation/lab_holdout/v2/evaluator_only/freeze-manifest.json).
The prior v1 generator remains byte-for-byte unchanged so its published freeze manifest still
resolves. The new generator is versioned independently for the same reason.

This is a synthetic lab confirmation set, not real incident history or measured production
recovery. The versioned [runner](../evaluation/run_confirmation_v2.py) and
[scorer](../evaluation/score_confirmation_v2.py) implement the new three-arm comparison. Both model
arms use transport profile 1.12. Runtime preflight checks dataset, plan, freeze, power, source,
provider and budget bindings without opening evaluator labels; the scorer opens labels only after
all 480 outcomes and runtime bindings validate. The complete protocol and exact hashes must be
frozen in the [comparison protocol](../evaluation/confirmation_v2/plan.json) before the first
Provider call. It binds three arms, rotation by dataset index, all 480 outcomes, DeepSeek Flash
settings, 6 physical/4 logical model and 12 read ceilings, failure retention, all scorer metrics,
the 15-point Top-1 effect threshold, zero critical safety defects and latency/cost gates. The
primary comparison is single model versus controlled graph; rules are a secondary reference.
Both entry points additionally reject protocol bytes that differ from the committed Git object.
The 480 older official results remain an immutable reference, not a new comparison arm.
