"""Add durable Prompt Registry lifecycle storage.

Revision ID: 20261004_0009
Revises: 20261004_0008
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261004_0009"
down_revision: str | None = "20261004_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["prompt_versions"].create(bind=bind)
    Base.metadata.tables["prompt_lifecycle_events"].create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["prompt_lifecycle_events"].drop(bind=bind)
    Base.metadata.tables["prompt_versions"].drop(bind=bind)
