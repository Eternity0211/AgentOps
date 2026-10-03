"""Add the transactional cross-process event outbox.

Revision ID: 20261003_0004
Revises: 20261003_0003
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261003_0004"
down_revision: str | None = "20261003_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create event intents independently from the later general job queue."""
    Base.metadata.tables["outbox_events"].create(bind=op.get_bind())


def downgrade() -> None:
    """Remove the outbox table."""
    Base.metadata.tables["outbox_events"].drop(bind=op.get_bind())
