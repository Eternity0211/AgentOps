"""Add immutable evidence-bound health verification runs.

Revision ID: 20261008_0015
Revises: 20261006_0014
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261008_0015"
down_revision: str | None = "20261006_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Older migrations construct tables from the current SQLAlchemy metadata, so a
    # clean install already receives this constraint when Evidence is created.
    # Existing installations at 0014 still need it added explicitly.
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname = 'uq_evidence_id_tenant_incident') THEN "
        "ALTER TABLE evidence ADD CONSTRAINT uq_evidence_id_tenant_incident "
        "UNIQUE (id, tenant_id, incident_id); "
        "END IF; END $$"
    )
    Base.metadata.tables["health_verification_runs"].create(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.tables["health_verification_runs"].drop(bind=op.get_bind())
    op.drop_constraint("uq_evidence_id_tenant_incident", "evidence", type_="unique")
