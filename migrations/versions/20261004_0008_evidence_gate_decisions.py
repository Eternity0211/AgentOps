"""Add immutable reproducible Evidence Gate decisions.

Revision ID: 20261004_0008
Revises: 20261003_0007
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261004_0008"
down_revision: str | None = "20261003_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tenant-scoped Evidence Gate decision snapshots."""
    Base.metadata.tables["evidence_gate_decisions"].create(bind=op.get_bind())


def downgrade() -> None:
    """Remove Evidence Gate decision snapshots."""
    Base.metadata.tables["evidence_gate_decisions"].drop(bind=op.get_bind())
