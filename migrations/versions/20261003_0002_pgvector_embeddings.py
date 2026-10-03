"""Enable pgvector and add versioned Incident memory embedding metadata.

Revision ID: 20261003_0002
Revises: 20261003_0001
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261003_0002"
down_revision: str | None = "20261003_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable vector types before creating embedding metadata."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.tables["incident_memory_embeddings"].create(bind=op.get_bind())


def downgrade() -> None:
    """Remove embedding storage and its isolated control-plane extension."""
    Base.metadata.tables["incident_memory_embeddings"].drop(bind=op.get_bind())
    op.execute("DROP EXTENSION IF EXISTS vector")
