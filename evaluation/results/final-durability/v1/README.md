# Final durability comparison v1

The frozen eight-pair census passed its safety acceptance on migrated local PostgreSQL. All 8/8
treatment routes matched the predeclared route; duplicate external effects were 0, ambiguous-result
redispatches were 0, and lost Evidence on resumable routes was 0. Median local total-latency delta
was +13 ms, with a deterministic paired bootstrap interval of [-32, +44] ms. Median takeover or
resume latency was +67 ms, interval [+25, +84] ms. These intervals describe this fixed local census
and do not establish production reliability or a positive/negative latency effect.

Every case in [the generated report](run-001/README.md) shows the uninterrupted control value,
treatment value and delta. [Raw observations](raw-run-001/observations.json) retain all sixteen
arms. The publication metadata binds the exact committed revision, frozen plan, probe source and
raw observation hashes.

The model and tool responses are controlled typed substitutes so physical calls, token counters,
Evidence persistence and replay can be observed exactly. No real human Approval or infrastructure
mutation occurs in this probe. Consequently this result measures the declared durability
mechanisms, not provider quality, human effort, MTTR, production availability or actual billing.
