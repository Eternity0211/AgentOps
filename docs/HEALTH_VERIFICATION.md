# Deterministic health-verification contract

Phase 9 begins with a framework-independent, versioned contract for deciding whether a completed
recovery action produced an observably stable service. It is a deterministic component, not an
agent, and it cannot accept a model success claim or confidence score.

## Scope and scenario binding

`HealthVerificationCriteria` binds the tenant, Incident, successful ActionExecution, service,
environment, server-resolved stable version, scenario, metric limits, zero-new-alert requirement,
stability-window duration, sampling-gap limit, rules version, and schema version. The closed MVP
scenario set contains only release-induced HTTP 500 and deployment-linked memory leak, the two
scenarios eligible for `rollback_service` under ADR 0005.

Release-induced HTTP 500 requires at least a 60-second stable window. Deployment-linked memory leak
requires at least 300 seconds so a momentary process response cannot masquerade as recovery. Both
remain capped at 3,600 seconds. Server rules permit no new alerts and bound sampling gaps to five
minutes or less; proposal thresholds cannot weaken these structural requirements.

## Immutable observations

`HealthVerificationObservation` binds the same authority scope and expected stable version. It
contains a strictly ordered, bounded sample sequence whose first and last timestamps exactly cover
the declared window. Every sample records integer-basis-point error rate, integer-millisecond P95
latency, health-endpoint status, deployed semantic version, and new-alert count.

Five distinct Evidence IDs bind the error-rate series, latency series, health endpoint, deployed
version, and alert query. Observation collection and expiry timestamps are explicit and UTC. The
next Phase 9 application batch must resolve those references against immutable, owned, fresh
Evidence and Artifact records before evaluation; IDs alone do not establish truth.

## Deterministic decision

`evaluate_health_verification` accepts only a `SUCCEEDED` ActionExecution and exact-scope criteria
and observation records. It evaluates reasons in fixed order:

1. observation expiry;
2. insufficient stability duration;
3. excessive sampling gap;
4. any error-rate breach;
5. any P95 latency breach;
6. any unhealthy endpoint sample;
7. any deployed-version mismatch; and
8. any new alert.

All samples must pass. A degraded intermediate sample therefore fails a flapping window even when
the first and last samples are healthy. A pass has no reasons; a failure retains every unique
applicable stable reason code. The decision binds criteria, observation, and ActionExecution
fingerprints plus a canonical combined input fingerprint, exact evaluation time, rules version,
and schema version.

This decision describes observed post-action health only. It does not transition the Incident,
enable the real mutation route, create compensation, or redeploy the known faulty version. Those
application routes remain separate deterministic work.

## Verification

Tests cover healthy release and memory-leak criteria, scenario-specific window floors, immutable
fingerprints, every individual reason in fixed order, intermediate flapping, missing coverage,
excessive gaps, stale observations, invalid numeric/type/version bounds, duplicate Evidence
references, time regression, non-successful actions, and cross-tenant/Incident/execution/service/
environment/version substitution. The contract module maintains complete statement and branch
coverage.
