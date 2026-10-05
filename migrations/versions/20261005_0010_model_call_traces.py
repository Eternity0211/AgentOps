"""Add content-free model-call traces and exact metering.

Revision ID: 20261005_0010
Revises: 20261004_0009
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261005_0010"
down_revision: str | None = "20261004_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["model_call_traces"].create(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.tables["model_call_traces"].drop(bind=op.get_bind())
