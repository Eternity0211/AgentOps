# Confirmed Incident Memory

Phase 7 uses a framework-independent projection for historical Incident memory. It is an
immutable advisory record, not Evidence for the current Incident and not a third decision agent.

## Admission boundary

`IncidentMemoryProjection.create` accepts only an authoritative `Incident` whose state is `CLOSED`
and whose closure time is present. Active, merely `RESOLVED`, cancelled, or otherwise non-closed
Incidents fail closed. The projection retains the owning tenant, source Incident ID, exact aggregate
version, `CLOSED` state, closure time, and projection time. The PostgreSQL adapter resolves and
rechecks those fields under a row lock before storing the projection; callers cannot use this
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

## Versioned embeddings and reindexing

`IncidentMemoryIndexer` separates generation from persistence through typed ports. Mock-model mode
uses a credential-free deterministic SHA-256 adapter that derives a bounded, L2-normalized vector
from the projection fingerprint; it does not retain or call out with root-cause text. Every vector
records provider, model, model version, dimensions, content schema, normalization version, source
fingerprint, and UTC creation time.

`IncidentMemoryRepository` resolves and locks the source Incident, verifies tenant, exact aggregate
version, `CLOSED` state, and closure timestamp, and writes the authoritative projection and vector
in one caller-owned transaction. A PostgreSQL trigger independently rejects direct vector inserts
whose Incident and source hash do not resolve to that projection. Exact model-identity replay is
idempotent. A new model or normalization identity inserts a new vector and explicitly marks prior
vectors for that Incident `reindex_required`; version identities are never silently overwritten.

## Scoped similarity retrieval

`SimilarIncidentRetriever` requires `EVIDENCE_READ` for the query tenant before storage access.
The PostgreSQL repository independently verifies that the current Incident belongs to that tenant,
then performs pgvector cosine search only across that tenant's authoritative projections. It
excludes the current Incident, future and out-of-window closures/projections, vectors marked for
reindex, incompatible provider/model/model-version/schema/normalization identities, dimension
mismatches, and negative similarity. Result counts are capped at 20 and ordered by distance,
closure time, then stable Incident ID.

The result type exposes only the historical Incident ID, service, bounded confirmed root-cause and
outcome summaries, closure time, similarity, and an invariant historical-only marker. It omits
tenant IDs, vectors, Evidence IDs/content, Diagnosis/Gate fingerprints, confirmation references,
and recovery-action references. Cross-tenant lookup fails without revealing whether memory exists.

These records remain `HISTORICAL_REFERENCE` and cannot satisfy current Evidence Gate facts. The
enabled `search_similar_incidents` adapter remains the next Phase 7 batch; scoped storage retrieval
alone does not grant model or Tool Gateway access.
