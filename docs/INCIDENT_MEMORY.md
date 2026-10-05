# Confirmed Incident Memory

Phase 7 begins with a framework-independent projection for historical Incident memory. It is an
immutable advisory record, not Evidence for the current Incident and not a third decision agent.

## Admission boundary

`IncidentMemoryProjection.create` accepts only an authoritative `Incident` whose state is `CLOSED`
and whose closure time is present. Active, merely `RESOLVED`, cancelled, or otherwise non-closed
Incidents fail closed. The projection retains the owning tenant, source Incident ID, exact aggregate
version, `CLOSED` state, closure time, and projection time. A later persistence adapter must resolve
and recheck those fields transactionally before storing the projection; callers cannot use this
contract to promote an arbitrary narrative into memory.

Every projection also retains:

- a normalized service and bounded single-line root-cause summary;
- a bounded, unique, canonically ordered set of source Evidence IDs;
- the exact Diagnosis Report and passing Evidence Gate decision fingerprints;
- either deterministic-verifier or human-review confirmation plus its authoritative reference;
- a typed `RECOVERED`, `HUMAN_RESOLVED`, or `NO_ACTION_REQUIRED` outcome and bounded summary; and
- a recovery-action reference only for `RECOVERED` outcomes.

## Trust and integrity

Trust is fixed to `HISTORICAL_REFERENCE`. Direct-observation, derived-observation, and untrusted
labels are rejected, so retrieval cannot relabel old experience as current evidence. Current
Incident diagnosis must still collect and resolve its own Evidence and pass the deterministic
Evidence Gate.

The `1.0.0` content fingerprint hashes canonical JSON containing all ownership, source, confirmation,
outcome, trust, version, text, reference, and timestamp fields. Evidence references are sorted before
hashing. Reordering them is stable; changing any authoritative field or post-construction text makes
the supplied fingerprint invalid. Text rejects control characters and is capped at 1,024 characters;
source Evidence is capped at 64 references.

## Verification

Unit tests cover canonical construction, normalization, Evidence ordering, all confirmation and
outcome combinations, exact size bounds, invalid text/service/time/reference types, active,
resolved, cancelled, and closed Incident admission, historical-only trust, schema/fingerprint
tampering, authority-metadata forgery, and immutability.

Embedding generation, storage, versioned reindexing, scoped similarity search, and the enabled
`search_similar_incidents` adapter remain separate Phase 7 batches.
