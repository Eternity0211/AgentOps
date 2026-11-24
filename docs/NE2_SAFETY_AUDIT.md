# NE2 safety instrumentation and frozen matrix

## Boundary

NE2 measures deterministic safety fixtures. It does not measure human
approval quality, production attack prevalence, real-world unsafe-action rate,
or recovery effectiveness. It does not change Evidence Gate rules, Policy,
Approval, Executor, verifier, or routing authority.

## Gate reason sidecar

`evaluation.gate_reason_audit` defines a label-free, create-separate sidecar
for future RCAEval development and confirmation runs. Every task in the bound
split must have exactly one entry. An entry is either `NOT_EVALUATED`, with no
fabricated decision data, or it retains the exact `PASS`/`FAIL`, Evidence Gate
1.1.0 reason codes, evaluated Evidence count, and decision fingerprint.

The sidecar binds its opaque audit ID, localization run ID, split, protocol
hash and task-index hash. Summarization rejects missing, extra or cross-split
cases and reports `NOT_EVALUATED` separately from Gate failure. It never reads
evaluator labels and never treats model confidence as authority.

## Frozen safety matrix

`evaluation/safety_matrix/v2/plan.json` freezes 13 semantic cases before the
measured run. It maps exact JUnit class/name pairs for:

- fabricated or altered Evidence references;
- tenant/Incident ownership substitution;
- stale, low-quality, non-independent, unresolved-counter and declared-missing Evidence;
- prompt injection quarantine;
- missing, rejected, expired, invalidated or materially changed Approval;
- replay and concurrent duplicate delivery;
- concurrent Approval decisions;
- refusal to close on failed or substituted verification;
- one authorized full-chain replay, the six-scenario terminal-route matrix,
  and a valid-Evidence normal control.

The report builder refuses absent mappings. A failure, error or skip produces
`NOT_VERIFIED`; it never becomes an observed zero. Only an entirely passing
semantic case can record zero for its predeclared prohibited outcomes. The
critical acceptance requires all cases verified plus zero unapproved
execution, duplicate execution and false recovery closure in their tested
fixtures.

## Measured deterministic result

Run 001 executed only after revision `fcdd0076` froze the instrumentation,
cases and acceptance. All 32 JUnit cases passed and map to 13/13 verified
semantic cases: 10/10 attacks, 2/2 safe-handoff/full-chain cases and 1/1
normal control. The report records zero unapproved execution across five
applicable semantic fixtures, zero duplicate execution across three, and zero
false recovery closure across three. Eight stable Evidence Gate reason codes
are exercised. The raw JUnit, generated JSON and reproduction record are in
`evaluation/results/safety-matrix/v2/run-001/`.

This completes the NE2 deterministic safety baseline. The zeroes have only
the stated fixture denominators. They are not production unsafe-action rates,
human approval observations or real-world recovery measurements.
