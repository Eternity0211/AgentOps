# Evidence-based post-core architecture decisions

All optional items are resolved for the current version without adding speculative capability.
MCP, another write tool, generic compensation, external anchoring, alternative stores/identity and
A2A are `NOT_REQUIRED` because their named prerequisites do not exist.

The queue decision uses the confirmatory control values. Four→eight PostgreSQL workers changed
median throughput 28.959→21.011 Jobs/s (-7.948, -27.4%) and queue-wait P95 1,866→2,608ms
(+742ms, +39.8%), with errors and duplicate ownership remaining 0→0. The current version therefore
retains PostgreSQL and caps the supported local configuration at four workers. Kafka/NATS remains
unadopted until an identical-workload candidate proves that it fixes the measured bottleneck
without weakening safety or audit semantics.
