"""Add immutable Approval invalidation markers.

Revision ID: 20261006_0013
Revises: 20261006_0012
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261006_0013"
down_revision: str | None = "20261006_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["approval_invalidations"].create(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.tables["approval_invalidations"].drop(bind=op.get_bind())
