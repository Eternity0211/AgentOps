# ADR 0002: LangGraph and PostgreSQL Durability

- Status: Accepted
- Date: 2026-10-01

## Context

The workflow needs typed branching, parallel read-only investigation, bounded replanning, human pauses, cancellation, crash recovery, and verification-driven rollback. The first version does not need a separate event broker.

## Decision

Use LangGraph for orchestration and PostgreSQL for checkpoints, domain persistence, outbox/audit data, and a transactional job claim/lease queue. Separate API and worker processes. Use bounded concurrency, heartbeats, lease expiry, attempt limits, and stale-job recovery.

## Consequences

Operations remain simple and transactional consistency is easier to demonstrate. PostgreSQL can become a throughput constraint; load tests will define observed limits. Kafka/NATS is deferred until measurements and delivery semantics justify it.

## Rejected alternatives

- In-process FastAPI background jobs: weak crash and deployment behavior.
- Kafka/NATS now: unnecessary operational complexity without measured need.
- Multiple orchestration frameworks: duplicated state semantics and testing burden.

## Verification

Integration tests cover concurrent claiming, lease expiry/takeover, worker crash/resume, cancel races, duplicate delivery, and checkpoint schema compatibility. Load reports state measured configuration and limits.
