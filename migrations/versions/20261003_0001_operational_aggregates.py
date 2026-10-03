"""Create initial Incident and Alert operational aggregates.

Revision ID: 20261003_0001
Revises: None
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261003_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tables in foreign-key dependency order."""
    bind = op.get_bind()
    for table_name in (
        "incidents",
        "incident_transitions",
        "incident_cancellation_requests",
        "alert_groups",
        "alerts",
    ):
        Base.metadata.tables[table_name].create(bind=bind)


def downgrade() -> None:
    """Drop tables in reverse foreign-key dependency order."""
    bind = op.get_bind()
    for table_name in (
        "alerts",
        "alert_groups",
        "incident_cancellation_requests",
        "incident_transitions",
        "incidents",
    ):
        Base.metadata.tables[table_name].drop(bind=bind)
