# Capacity and scaling pilot v2

This frozen pilot runs the same 64-job PostgreSQL claim/lease workload with 1, 2, 4 and 8 workers,
three times per level. It records individual queue and workflow timings plus exact local process,
Python heap and SQL-statement observations. The pilot sizes a separate confirmatory run; it cannot
itself close FC10 or justify a broker.

Correctness remains non-negotiable: every Job must complete once with no duplicate ownership. A
failure is reported as a failure, not converted into a scaling result. Kafka or NATS is considered
only if the confirmatory run crosses the predeclared joint throughput/queue-wait bottleneck rule.
The resource scope excludes PostgreSQL/container CPU and memory, so the report must not claim
whole-system capacity or production throughput.
