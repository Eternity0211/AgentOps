# Live memory runtime audit v1

The committed implementation was exercised against the real local Docker simulator and the
Tempo/Loki/deployment read path. Both runs issued six faulted checkouts, cleaned the evaluator
fault in `finally`, and verified a post-cleanup HTTP 200. Evaluator cleanup has
`recovery_credit=false`.

Run 001 is retained as a failed capture: all six requests, Loki data, deployment 2.0.0 and cleanup
succeeded, but the original fixed six-second wait returned an empty Tempo trace result. It has no
memory facts and cannot satisfy GC/retention acceptance. The runner was then changed in a separate
commit to poll Tempo for at most 30 seconds and to publish an explicit all-of acceptance map.

Run 002 passed every declared capture check. The candidate context observed six ordered memory
samples, one complete GC pair, five net allocations, zero releases and
`SUSTAINED_RETENTION`; the raw observations include the release counter, deployment version 2.0.0,
and six HTTP 200 checkouts. Cleanup returned zero and the post-cleanup checkout was HTTP 200. The
context admitted 15,546 of 24,000 bytes (1,441 compact-fact bytes); the large raw log observation
was excluded while its trace/deployment-derived compact evidence remained referenceable.

This audit proves the local transport and bounded context mechanism. It is not a diagnosis-quality,
production incidence, MTTR, billing, or recovery claim.
