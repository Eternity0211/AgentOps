"""Add tenant-contiguous audit sequencing and event fingerprints.

Revision ID: 20261016_0023
Revises: 20261015_0022
Create Date: 2026-10-16
"""

from collections.abc import Mapping, Sequence
from typing import Any, cast

import sqlalchemy as sa
from alembic import op

from agentops_incident_commander.domain import (
    ActorId,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    audit_event_fingerprint,
)
from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261016_0023"
down_revision: str | None = "20261015_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _event_from_row(row: Mapping[str, Any]) -> AuditEvent:
    return AuditEvent(
        id=AuditEventId(row["id"]),
        tenant_id=TenantId(row["tenant_id"]),
        type=row["event_type"],
        event_version=row["event_version"],
        payload_schema_version=row["payload_schema_version"],
        actor_id=ActorId(row["actor_id"]),
        correlation_id=CorrelationId(row["correlation_id"]),
        causation_id=CausationId(row["causation_id"]),
        target=AuditTarget(row["target_type"], OpaqueIdentifier(row["target_id"])),
        occurred_at=row["occurred_at"],
        request_hash=(None if row["request_hash"] is None else Sha256Digest(row["request_hash"])),
        result_hash=None if row["result_hash"] is None else Sha256Digest(row["result_hash"]),
    )


def upgrade() -> None:
    """Backfill immutable integrity metadata and install concurrency-safe assignment."""
    Base.metadata.tables["audit_tenant_sequences"].create(bind=op.get_bind())
    # Historical migrations create selected tables from current metadata. The guarded
    # additions keep both a genuinely old database and a clean replay deterministic.
    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS tenant_sequence BIGINT")
    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS event_fingerprint VARCHAR(64)")

    op.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_reject_row_mutation")
    op.execute(
        """
        WITH numbered AS (
            SELECT sequence,
                   row_number() OVER (PARTITION BY tenant_id ORDER BY sequence) AS tenant_sequence
            FROM audit_events
        )
        UPDATE audit_events AS events
        SET tenant_sequence = numbered.tenant_sequence
        FROM numbered
        WHERE events.sequence = numbered.sequence
        """
    )
    connection = op.get_bind()
    rows = list(
        connection.execute(
            sa.text(
                "SELECT id, tenant_id, event_type, event_version, payload_schema_version, "
                "actor_id, correlation_id, causation_id, target_type, target_id, request_hash, "
                "result_hash, occurred_at FROM audit_events ORDER BY sequence"
            )
        ).mappings()
    )
    for row in rows:
        connection.execute(
            sa.text(
                "UPDATE audit_events SET event_fingerprint = :fingerprint WHERE id = :event_id"
            ),
            {
                "event_id": row["id"],
                "fingerprint": audit_event_fingerprint(
                    _event_from_row(cast(Mapping[str, Any], row))
                ).value,
            },
        )
    op.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_reject_row_mutation")

    op.alter_column("audit_events", "tenant_sequence", nullable=False)
    op.alter_column("audit_events", "event_fingerprint", nullable=False)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_audit_event_fingerprint'
                  AND conrelid = 'audit_events'::regclass
            ) THEN
                ALTER TABLE audit_events
                ADD CONSTRAINT ck_audit_event_fingerprint
                CHECK (event_fingerprint ~ '^[0-9a-f]{64}$');
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_audit_tenant_sequence'
                  AND conrelid = 'audit_events'::regclass
            ) THEN
                ALTER TABLE audit_events
                ADD CONSTRAINT uq_audit_tenant_sequence
                UNIQUE (tenant_id, tenant_sequence);
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        INSERT INTO audit_tenant_sequences (tenant_id, last_sequence)
        SELECT tenant_id, max(tenant_sequence)
        FROM audit_events
        GROUP BY tenant_id
        """
    )
    op.execute(
        """
        CREATE FUNCTION assign_audit_tenant_sequence()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF NEW.tenant_sequence IS NOT NULL THEN
                RAISE EXCEPTION 'audit tenant sequence is database assigned'
                    USING ERRCODE = '55000';
            END IF;
            INSERT INTO public.audit_tenant_sequences AS heads (tenant_id, last_sequence)
            VALUES (NEW.tenant_id, 1)
            ON CONFLICT (tenant_id) DO UPDATE
            SET last_sequence = heads.last_sequence + 1
            RETURNING last_sequence INTO NEW.tenant_sequence;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION assign_audit_tenant_sequence() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER audit_events_assign_tenant_sequence
        BEFORE INSERT ON audit_events
        FOR EACH ROW EXECUTE FUNCTION assign_audit_tenant_sequence()
        """
    )
    op.execute("REVOKE ALL ON audit_tenant_sequences FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM PUBLIC")


def downgrade() -> None:
    """Remove integrity metadata while retaining the original append-only protections."""
    op.execute("DROP TRIGGER audit_events_assign_tenant_sequence ON audit_events")
    op.execute("DROP FUNCTION assign_audit_tenant_sequence()")
    op.drop_constraint("uq_audit_tenant_sequence", "audit_events", type_="unique")
    op.drop_constraint("ck_audit_event_fingerprint", "audit_events", type_="check")
    op.drop_column("audit_events", "event_fingerprint")
    op.drop_column("audit_events", "tenant_sequence")
    Base.metadata.tables["audit_tenant_sequences"].drop(bind=op.get_bind())
