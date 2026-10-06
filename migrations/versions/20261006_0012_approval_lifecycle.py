"""Add proposal-bound Approval lifecycle storage.

Revision ID: 20261006_0012
Revises: 20261005_0011
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261006_0012"
down_revision: str | None = "20261005_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["approvals"].create(bind=bind)
    Base.metadata.tables["approval_lifecycle_events"].create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["approval_lifecycle_events"].drop(bind=bind)
    Base.metadata.tables["approvals"].drop(bind=bind)
