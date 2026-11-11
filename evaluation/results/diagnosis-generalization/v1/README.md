# Diagnosis generalization replay v1

This result is a bounded follow-up to the 81-case diagnosis-quality retest. It does not alter
that score. Inputs and evaluator labels were committed separately before the provider calls.

`run-001` preserves the first v5 replay attempt: one call returned `INVALID_RESPONSE`, the old
runner stopped before persisting its in-memory event, and the other four cases were not called.
Its usage and response hash are irrecoverably unknown.

`run-002` completed five calls with immediate per-case persistence. All three controls (normal,
two-sample rise, and deployment-only) safely handed off. Neither positive case hit `memory-leak`:
the v5 Evidence replay again failed because the explanation exceeded the schema limit, while the
new three-sample rise was described correctly but conservatively handed off because the short
window, sub-limit values, and missing alert linkage did not establish a leak. Positive Top-1 is
therefore 0/2, not a fix claim.

The run retained 14,983 input and 1,023 output tokens. The deterministic rate-card reservation is
5,722,500 nanodollars; actual provider billing is unknown. Per-case isolated timing covers evidence
loading, context construction, and model invocation. Totals were 0 ms, 78 ms, and 10,453 ms;
millisecond rounding makes the synthetic evidence-load and context stages appear as zero. Sorted
whole-case durations were 1,813–2,906 ms. These are local experiment timings, not human MTTR.

No approval, infrastructure write, recovery, or closure occurred. The following require separate
future measurements and remain unknown:

- Human approval: use authorized operators and record proposal-ready to decision latency, expiry,
  rejection, mutation invalidation, and decision agreement. No simulated approval is a substitute.
- Human labor: use observer-recorded active minutes in a blinded crossover study; do not infer
  labor saved from model or workflow duration.
- Billing: reconcile provider invoices to retained request hashes and usage records; the local
  rate card is only an upper-bound reservation.
- Real incident history: populate only confirmed closed-incident projections with tenant-scoped
  authorization and compare against the identical no-history runner. No such history was supplied.
- External data quality, operator availability, production network latency, and downstream service
  behavior were outside this isolated replay and remain unmeasured.

The non-bypassable product chain remains unchanged. These diagnosis-only runs stop before
remediation, policy, approval, execution, verification, and closure.
