# ADR 0010: Post-core options and bounded PostgreSQL worker cap

- Status: Accepted
- Date: 2026-11-13

## Context

FC12 requires evidence before adding MCP, another write tool, generic compensation, external audit
anchoring, alternative Artifact/identity infrastructure, a broker, or A2A. The confirmatory local
PostgreSQL queue run completed eleven repetitions at each of 1, 2, 4 and 8 workers. Median
throughput was 17.227, 28.946, 28.959 and 21.011 Jobs/s; errors and duplicate ownership were zero.
From four to eight workers, throughput changed by -7.948 Jobs/s (-27.4%) and queue-wait P95 changed
from 1,866 to 2,608 ms (+742 ms, +39.8%). This crossed the predeclared trigger for evaluating a
broker or queue alternative, but no Kafka/NATS candidate has yet demonstrated better ordering,
replay, audit, safety, cost, or operations on the identical workload.

No current deployment requirement names an MCP-only integration, a second reversible write action,
an independent compensation policy/inverse, an external audit-anchor threat, an alternative object
store, enterprise identity, or independently deployed/owned decision-agent protocol boundary.

## Decision

Keep PostgreSQL as the current control-plane queue and cap the supported local worker configuration
at four. Eight workers are not a supported scaling recommendation. The threshold crossing creates
a future comparison requirement; it does not authorize Kafka or NATS. A broker may supersede this
decision only after an identical-workload comparison demonstrates the required improvement without
weakening ordering, idempotency, replay, tenant isolation, or append-only audit semantics and a new
ADR accepts its operational cost.

For the current version, read-only MCP, another write tool, generic compensation, external audit
anchoring, alternative Artifact stores, enterprise identity, and A2A are `NOT_REQUIRED`. Existing
ports remain extension points; absence of a current requirement is not evidence that those options
can never be useful.

## Consequences

The current supported choice is deliberately bounded rather than maximally scalable. Two workers
improved median throughput by 68.0% and four by 68.1% relative to one worker in the confirmatory
medians, while eight regressed relative to four. Operations retain one transactional persistence
system and the proven safety semantics. Production capacity, database CPU/memory, cloud cost and
availability remain unmeasured, so this ADR cannot set a production worker count.

## Alternatives

- Add Kafka/NATS now: rejected because the trigger establishes a need for comparison, not proof that
  either candidate fixes it safely or economically.
- Claim eight-worker horizontal scale: rejected by the measured throughput and queue-wait regression.
- Add every optional integration behind unused abstractions: rejected because it increases attack
  surface and operational complexity without a named requirement.

## Verification

`evaluation/results/final-load/v1/confirmatory-001/confirmatory.json` retains all 44 runs and the
frozen decision. `evaluation/results/architecture-decisions/v1/decisions.json` binds each option to
its requirement and evidence disposition. Tests recompute the load result and reject an adopted
broker or optional capability without its required evidence.
