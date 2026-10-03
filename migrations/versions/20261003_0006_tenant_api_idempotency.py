"""Add tenant-scoped API ownership and durable command idempotency.

Revision ID: 20261003_0006
Revises: 20261003_0005
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261003_0006"
down_revision: str | None = "20261003_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Isolate legacy records, add tenant indexes, and create the replay ledger."""
    bind = op.get_bind()
    op.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128)")
    op.execute(
        "UPDATE incidents SET tenant_id = COALESCE((SELECT CASE "
        "WHEN COUNT(DISTINCT tenant_id) = 1 THEN MIN(tenant_id) END FROM alert_groups "
        "WHERE alert_groups.incident_id = incidents.id), 'legacy-unassigned') "
        "WHERE tenant_id IS NULL"
    )
    op.execute("ALTER TABLE incidents ALTER COLUMN tenant_id SET NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_incidents_tenant_opened "
        "ON incidents (tenant_id, opened_at, id)"
    )

    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128)")
    op.execute(
        "UPDATE audit_events SET tenant_id = COALESCE((SELECT tenant_id FROM incidents "
        "WHERE audit_events.target_type IN ('incident.record', 'incident.lifecycle') "
        "AND incidents.id = audit_events.target_id), 'legacy-unassigned') "
        "WHERE tenant_id IS NULL"
    )
    op.execute("ALTER TABLE audit_events ALTER COLUMN tenant_id SET NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_tenant_sequence ON audit_events (tenant_id, sequence)"
    )
    Base.metadata.tables["idempotency_records"].create(bind=bind)


def downgrade() -> None:
    """Remove API idempotency and tenant ownership introduced by this revision."""
    bind = op.get_bind()
    Base.metadata.tables["idempotency_records"].drop(bind=bind)
    op.execute("DROP INDEX IF EXISTS ix_audit_tenant_sequence")
    op.drop_column("audit_events", "tenant_id")
    op.execute("DROP INDEX IF EXISTS ix_incidents_tenant_opened")
    op.drop_column("incidents", "tenant_id")
