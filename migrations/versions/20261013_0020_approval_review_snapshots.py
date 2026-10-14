"""Add immutable Approval review snapshots and replacement proposal content.

Revision ID: 20261013_0020
Revises: 20261013_0019
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_0020"
down_revision: str | None = "20261013_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_review_snapshots",
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("incident_id", sa.String(length=128), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="ck_approval_review_document"),
        sa.CheckConstraint(
            "snapshot_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_approval_review_hash"
        ),
        sa.ForeignKeyConstraint(
            ["approval_id", "tenant_id"],
            ["approvals.id", "approvals.tenant_id"],
            name="fk_approval_review_approval_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index(
        "ix_approval_review_incident",
        "approval_review_snapshots",
        ["tenant_id", "incident_id"],
        unique=False,
    )
    # Older migrations create this table from live metadata, so fresh databases
    # may already contain the additive column while upgraded databases do not.
    op.execute(
        "ALTER TABLE approval_invalidations ADD COLUMN IF NOT EXISTS replacement_proposal JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE approval_invalidations DROP COLUMN IF EXISTS replacement_proposal")
    op.drop_index("ix_approval_review_incident", table_name="approval_review_snapshots")
    op.drop_table("approval_review_snapshots")
