"""Add production federated identity and tenant membership tables.

Revision ID: 20261127_0024
Revises: 20261016_0023
Create Date: 2026-11-27
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261127_0024"
down_revision: str | None = "20261016_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create identity tables in foreign-key dependency order."""
    for name in ("tenants", "identity_users", "federated_identities", "tenant_memberships"):
        Base.metadata.tables[name].create(bind=op.get_bind())


def downgrade() -> None:
    """Remove only the identity boundary introduced by this revision."""
    for name in ("tenant_memberships", "federated_identities", "identity_users", "tenants"):
        Base.metadata.tables[name].drop(bind=op.get_bind())
