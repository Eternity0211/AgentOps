# Immutable Artifact Storage

Phase 3 begins with a framework-independent `ArtifactStorage` port and a local development
adapter. Artifacts keep large or raw payloads outside workflow state while preserving a stable,
auditable reference.

## Metadata contract

Every Artifact has an opaque ID, tenant and Incident ownership, a server-generated locator,
canonical media type, content and metadata schema versions, SHA-256 digest, exact byte size,
UTC creation/expiry timestamps, retention class, redaction status, and encryption status. The
metadata schema is version `1.0.0`. `TRANSIENT` objects require an expiry; `INCIDENT` and `AUDIT`
objects may use an explicit expiry or an administrator-managed lifecycle.

The local adapter stores content by SHA-256 and creates a separate immutable metadata document
for each Artifact ID. Reusing an ID is rejected, including concurrent creation. Reusing identical
content under a different ID is safe and deduplicates the content-addressed blob. Reads recompute
both hash and size, so missing or altered bytes fail integrity verification.

## Authorization and path safety

Retrieval requires a validated principal with `evidence:read`, a matching tenant, and the owning
Incident ID. Anonymous, cross-tenant, cross-Incident, expired, missing, and corrupt reads fail
closed. The adapter derives every path from validated opaque IDs and digests; clients cannot
supply a path. The configured root, internal directories, and object paths are containment-checked
and symbolic-link objects are rejected.

The local backend is for development and tests. It does not claim encryption at rest; that fact is
recorded as `encrypted=false`. A production object-store adapter must implement the same port,
retain server-side authorization, use create-only writes/version locking, and report its actual
encryption and retention controls. Ground Truth paths and evaluator credentials are never valid
Artifact roots or runtime inputs.

## Current boundary

This batch intentionally does not add Evidence records, collectors, retention deletion jobs, or
HTTP endpoints. Those remain separate Phase 3 batches. Expiry blocks payload retrieval but does
not silently remove immutable metadata or audit-integrity references.
