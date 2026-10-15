"""Add the tenant-scoped immutable correlation ledger.

Revision ID: 20261015_0021
Revises: 20261013_0020
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0021"
down_revision: str | None = "20261013_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "correlation_streams",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("incident_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("schema_version = '1.0.0'", name="ck_correlation_stream_schema"),
        sa.ForeignKeyConstraint(
            ["incident_id", "tenant_id"],
            ["incidents.id", "incidents.tenant_id"],
            name="fk_correlation_stream_incident_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "correlation_id"),
        sa.UniqueConstraint(
            "tenant_id", "correlation_id", "incident_id", name="uq_correlation_stream_scope"
        ),
    )
    op.create_index(
        "ix_correlation_stream_incident",
        "correlation_streams",
        ["tenant_id", "incident_id"],
    )
    op.create_table(
        "correlation_links",
        sa.Column("sequence", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("incident_id", sa.String(length=128), nullable=False),
        sa.Column("component", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("causation_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "component IN ('ALERT', 'INCIDENT', 'GRAPH', 'TOOL', 'MODEL', 'APPROVAL', "
            "'EXECUTION', 'VERIFICATION')",
            name="ck_correlation_link_component",
        ),
        sa.CheckConstraint(
            "trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32)",
            name="ck_correlation_link_trace_id",
        ),
        sa.CheckConstraint(
            "(causation_id IS NULL AND component = 'ALERT') OR causation_id IS NOT NULL",
            name="ck_correlation_link_root",
        ),
        sa.CheckConstraint("schema_version = '1.0.0'", name="ck_correlation_link_schema"),
        sa.CheckConstraint(
            "fingerprint ~ '^[0-9a-f]{64}$'", name="ck_correlation_link_fingerprint"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "correlation_id", "incident_id"],
            [
                "correlation_streams.tenant_id",
                "correlation_streams.correlation_id",
                "correlation_streams.incident_id",
            ],
            name="fk_correlation_link_stream_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "correlation_id", "causation_id"],
            [
                "correlation_links.tenant_id",
                "correlation_links.correlation_id",
                "correlation_links.event_id",
            ],
            name="fk_correlation_link_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("sequence"),
        sa.UniqueConstraint("event_id", name="uq_correlation_link_event"),
        sa.UniqueConstraint(
            "tenant_id", "correlation_id", "event_id", name="uq_correlation_link_stream_event"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "correlation_id",
            "component",
            "resource_id",
            name="uq_correlation_link_resource",
        ),
    )
    op.create_index(
        "ix_correlation_link_incident_sequence",
        "correlation_links",
        ["tenant_id", "incident_id", "sequence"],
    )
    op.create_index(
        "ix_correlation_link_stream_sequence",
        "correlation_links",
        ["tenant_id", "correlation_id", "sequence"],
    )
    op.create_index("ix_correlation_link_trace", "correlation_links", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_correlation_link_trace", table_name="correlation_links")
    op.drop_index("ix_correlation_link_stream_sequence", table_name="correlation_links")
    op.drop_index("ix_correlation_link_incident_sequence", table_name="correlation_links")
    op.drop_table("correlation_links")
    op.drop_index("ix_correlation_stream_incident", table_name="correlation_streams")
    op.drop_table("correlation_streams")
