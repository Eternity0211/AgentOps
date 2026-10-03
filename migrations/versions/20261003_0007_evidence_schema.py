"""Add immutable tenant-scoped Evidence records.

Revision ID: 20261003_0007
Revises: 20261003_0006
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261003_0007"
down_revision: str | None = "20261003_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create Evidence with database-enforced Incident tenant ownership."""
    bind = op.get_bind()
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname = 'uq_incidents_id_tenant') THEN "
        "ALTER TABLE incidents ADD CONSTRAINT uq_incidents_id_tenant UNIQUE (id, tenant_id); "
        "END IF; END $$"
    )
    Base.metadata.tables["evidence"].create(bind=bind)


def downgrade() -> None:
    """Remove Evidence and its composite Incident ownership key."""
    bind = op.get_bind()
    Base.metadata.tables["evidence"].drop(bind=bind)
    op.execute("ALTER TABLE incidents DROP CONSTRAINT IF EXISTS uq_incidents_id_tenant")
