# NE4 independent confirmation readiness

NE4 cannot be frozen or run until the exact RCAEval source revision is locally available.
The required `cases.parquet` hash is
`ec0008c90d0c97076bc98370ac824c3c5a49be95d00bd6d6044ea8061861d271`, and the
180 RE2-OB/RE2-TT task files must be exported from revision
`8b6c06a7a15bcecdbf70b611a13b789c5925dc17` before any provider call.

On 2026-11-24, four direct download attempts from the authoritative Hugging Face repository
timed out before a TLS connection was established. No pinned index, telemetry tree, or task
export exists locally. Browser-visible documentation is insufficient because it cannot satisfy
the byte hash or telemetry bindings. A mirror, current branch, synthetic substitute, or the old
confirmation-v2 cohort would violate the frozen protocol.

The versioned preflight reports all prerequisites without reading evaluator labels or exposing
the provider credential. Its recorded blocked result confirms that the credential is available,
while the source index, telemetry root, and task export are missing. It also records that the old
480 confirmation outcomes were not touched.

The label-free run path is now partially implemented independently of source availability.
`rcaeval_features.py` verifies every bound Parquet file and emits a bounded five-service context.
The baseline contains post-injection aggregates; the candidate adds deterministic pre/post deltas
for the same metrics, log counts, trace counts, error counts and durations. Both use at most 14 of
the frozen 24 read calls, retain missing-modality and truncation metadata, and never accept an
answer path. `rcaeval_provider.py` uses identical DeepSeek settings for both arms, validates the
typed service ranking, permits only one bounded schema repair, enforces the two-call and token
budgets, and journals hashes and resource totals without provider bodies or credentials. These
components are tested with bound Parquet fixtures and a mock transport; they are not a measured
external result.

NE4 therefore remains open. When authoritative bytes become reachable, the next batch must:

1. verify the index hash and export all 180 label-free tasks;
2. finish the create-once interleaved runner, then freeze task-index, runner/scorer sources, arms,
   budgets, interleaving, safety/resource ceilings,
   failure policy, and 95% intervals in a committed plan before calls;
3. run every holdout pair once, preserve all outcomes, then open evaluator-only answers; and
4. publish null or adverse results exactly as observed.
