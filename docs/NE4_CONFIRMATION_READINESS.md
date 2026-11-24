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

NE4 therefore remains open. When authoritative bytes become reachable, the next batch must:

1. verify the index hash and export all 180 label-free tasks;
2. freeze task-index, runner/scorer sources, arms, budgets, interleaving, safety/resource ceilings,
   failure policy, and 95% intervals in a committed plan before calls;
3. run every holdout pair once, preserve all outcomes, then open evaluator-only answers; and
4. publish null or adverse results exactly as observed.
