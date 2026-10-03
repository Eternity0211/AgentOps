"""Add the PostgreSQL claim/lease worker queue.

Revision ID: 20261003_0005
Revises: 20261003_0004
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261003_0005"
down_revision: str | None = "20261003_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable job queue independently from outbox delivery."""
    Base.metadata.tables["jobs"].create(bind=op.get_bind())


def downgrade() -> None:
    """Remove the durable job queue."""
    Base.metadata.tables["jobs"].drop(bind=op.get_bind())
