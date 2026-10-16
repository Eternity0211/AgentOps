# Audit ledger integrity, export, and retention

The audit ledger records actor and control-plane facts without storing request or result bodies.
It is evidence of what the platform persisted; it is not an execution authority, an Evidence Store,
or an externally anchored tamper-proof log. The current contracts are `audit-integrity/v1` for event
fingerprints and `audit-export/v1` for export-page manifests.

## Storage and ordering

Every `audit_events` row has two database-assigned identifiers:

- `sequence` is the PostgreSQL-wide ordering value. It is useful for internal chronology but can
  contain gaps caused by rolled-back transactions and is not an export cursor.
- `tenant_sequence` is a contiguous per-tenant value assigned by a `SECURITY DEFINER` trigger. The
  trigger updates a private `audit_tenant_sequences` head in the same transaction as the insert, so
  rollback cannot consume a tenant value. Callers cannot supply this value.

The stable Event ID rejects logical replay. A canonical SHA-256 `event_fingerprint` covers the
integrity schema version plus tenant, Event ID/type/version, payload schema, actor, correlation,
causation, target, UTC occurrence time, and optional request/result hashes. Every repository read
reconstructs the typed event and recomputes that fingerprint. Fingerprint mismatch fails closed.

The tenant head lets an export detect a deleted trailing record as well as an internal gap. A page
also rejects a non-contiguous first record, duplicate global sequence, duplicate Event ID,
cross-tenant record, or invalid event fingerprint. The mechanism does not claim hash chaining or
external anchoring; a database owner remains inside the trusted administration boundary. Stronger
anchoring is an explicitly tracked post-core enhancement.

## Database permission boundary

Migration `20261016_0023` revokes all public access to `audit_tenant_sequences`, revokes public
`UPDATE`, `DELETE`, and `TRUNCATE` on `audit_events`, and retains owner-visible mutation-rejection
triggers. A deployment must grant its non-owner application role only the audit privileges it
needs. The audit-specific portion of that grant is:

```sql
GRANT USAGE ON SCHEMA public TO agentops_runtime;
GRANT SELECT, INSERT ON audit_events TO agentops_runtime;
GRANT SELECT ON audit_tenant_sequences TO agentops_runtime;
GRANT USAGE, SELECT ON SEQUENCE audit_events_sequence_seq TO agentops_runtime;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM agentops_runtime;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit_tenant_sequences FROM agentops_runtime;
```

The application may read a tenant head for verified export but cannot insert, update, delete, or
truncate head rows. The trigger performs the only head mutation through its security-definer path.
Local development currently connects with the migration owner, so the mutation triggers remain
the local defense. The complete production role split and credential validation remain Phase 13
work; this batch proves the audit-specific grants with a temporary non-owner PostgreSQL role and
does not claim the entire Compose database role is least privilege.

Corrections are new events. Application code must never rewrite a historical event. Operational
database owners must not disable the triggers except in an audited, tested migration or recovery
procedure.

## Authorized export

`GET /api/v1/audit` requires `audit:read`, always derives the Tenant ID from the authenticated
principal, and accepts `after_sequence` plus a page `limit` from 1 through 100. Here,
`after_sequence` means the last verified `tenant_sequence`, not the global sequence.

Each item exposes both sequences and the stored event fingerprint. Each response also includes an
`audit-export/v1` manifest containing tenant, input cursor, first/last tenant sequence, item count,
next cursor, and a page fingerprint. The page fingerprint is SHA-256 over canonical JSON containing
the schema version, Tenant ID, input cursor, continuation state, and for each ordered item its Event
ID, global sequence, tenant sequence, and event fingerprint. Replaying an unchanged page produces
the same manifest.

An exporter must:

1. authenticate with `audit:read`, start at `after_sequence=0`, and persist the complete response;
2. verify that the first item is cursor plus one, all tenant sequences are consecutive, and the
   item count and range match the manifest;
3. recompute each event fingerprint and the canonical page fingerprint;
4. follow `next_after_sequence` unchanged until it is `null`;
5. preserve pages and manifests together, then record export time, deployment identity,
   destination, encryption, operator, and final tenant sequence in the deployment-owned register.

The endpoint returns `AUDIT_INTEGRITY_FAILED` instead of partial history when persisted data cannot
be verified. Export is read-only and does not mark, mutate, expire, or delete ledger rows.

## Retention, archive, and legal hold

The core repository does not automate audit deletion or claim an external archive. In the
reference deployment audit rows and tenant heads remain online indefinitely. A production owner
must define jurisdiction-specific online retention, encrypted archive destination, access roles,
key lifecycle, restoration test frequency, and deletion authorization before setting a finite
period.

Legal hold overrides scheduled expiry and archive deletion. A hold must identify the tenant and
Incident/time scope, authority, start time, review owner, and release authorization outside the
application role. Archive verification must replay the manifests and compare the last exported
tenant sequence with the online head. Only a privileged, separately audited retention procedure
may remove eligible online data after a verified archive and hold check; no such deletion procedure
ships in the core version. Removing rows without rebuilding and independently attesting the stream
would intentionally make subsequent export fail closed.

## Verification

Unit tests cover canonical fingerprints, invalid stored records, tenant isolation, continuity,
duplicates, manifest construction, replay, bounds, and malformed contracts. PostgreSQL integration
tests cover clean migration upgrade/downgrade, concurrent assignment, audit-specific non-owner
permissions, owner-trigger protection, raw hash rejection, deterministic page replay, cursor/head
checks, fingerprint tampering, sequence gaps, and deleted tails.
