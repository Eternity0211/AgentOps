"""Add durable recovery action executions and target locks.

Revision ID: 20261006_0014
Revises: 20261006_0013
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261006_0014"
down_revision: str | None = "20261006_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["action_executions"].create(bind=bind)
    Base.metadata.tables["action_execution_locks"].create(bind=bind)
    Base.metadata.tables["action_execution_events"].create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["action_execution_events"].drop(bind=bind)
    Base.metadata.tables["action_execution_locks"].drop(bind=bind)
    Base.metadata.tables["action_executions"].drop(bind=bind)
