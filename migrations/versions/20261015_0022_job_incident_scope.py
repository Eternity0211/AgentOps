"""Bind durable jobs to tenant, Incident, and workflow identity.

Revision ID: 20261015_0022
Revises: 20261015_0021
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0022"
down_revision: str | None = "20261015_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Require resolvable ownership before a job can emit scoped telemetry."""
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("jobs")}
    required = {"tenant_id", "incident_id", "workflow_run_id"}
    if not required.issubset(columns):
        existing: bool = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM jobs)")).scalar_one()
        if existing:
            raise RuntimeError("job scope migration requires the durable job queue to be drained")
        for name in ("tenant_id", "incident_id", "workflow_run_id"):
            if name not in columns:
                op.add_column("jobs", sa.Column(name, sa.String(length=128), nullable=False))

    foreign_keys = {item["name"] for item in sa.inspect(bind).get_foreign_keys("jobs")}
    if "fk_jobs_incident_tenant" not in foreign_keys:
        op.create_foreign_key(
            "fk_jobs_incident_tenant",
            "jobs",
            "incidents",
            ["incident_id", "tenant_id"],
            ["id", "tenant_id"],
            ondelete="RESTRICT",
        )
    op.drop_constraint("ck_jobs_max_attempts", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_max_attempts",
        "jobs",
        "max_attempts BETWEEN 1 AND 128",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_incident ON jobs (tenant_id, incident_id, sequence)"
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_max_attempts", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_max_attempts", "jobs", "max_attempts >= 1")
    op.execute("DROP INDEX IF EXISTS ix_jobs_incident")
    foreign_keys = {item["name"] for item in sa.inspect(op.get_bind()).get_foreign_keys("jobs")}
    if "fk_jobs_incident_tenant" in foreign_keys:
        op.drop_constraint("fk_jobs_incident_tenant", "jobs", type_="foreignkey")
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("jobs")}
    for name in ("workflow_run_id", "incident_id", "tenant_id"):
        if name in columns:
            op.drop_column("jobs", name)
