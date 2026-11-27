"""Add one-time OIDC login transactions and revocable browser sessions.

Revision ID: 20261127_0025
Revises: 20261127_0024
Create Date: 2026-11-27
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261127_0025"
down_revision: str | None = "20261127_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("oidc_login_attempts", "browser_sessions"):
        Base.metadata.tables[name].create(bind=op.get_bind())


def downgrade() -> None:
    for name in ("browser_sessions", "oidc_login_attempts"):
        Base.metadata.tables[name].drop(bind=op.get_bind())
