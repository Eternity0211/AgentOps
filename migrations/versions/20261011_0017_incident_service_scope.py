"""Persist the Incident service scope required by list and detail contracts.

Revision ID: 20261011_0017
Revises: 20261009_0016
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_0017"
down_revision: str | None = "20261009_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS service VARCHAR(128)")
    op.execute(
        """
        UPDATE incidents
        SET service = source.service
        FROM (
            SELECT incident_id, MIN(service) AS service
            FROM alert_groups
            WHERE incident_id IS NOT NULL
            GROUP BY incident_id
        ) AS source
        WHERE incidents.id = source.incident_id AND incidents.service IS NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM incidents WHERE service IS NULL) THEN
                RAISE EXCEPTION 'cannot migrate Incident without an Alert Group service scope';
            END IF;
        END
        $$
        """
    )
    op.execute("ALTER TABLE incidents ALTER COLUMN service SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_incidents_service'
            ) THEN
                ALTER TABLE incidents ADD CONSTRAINT ck_incidents_service
                CHECK (service ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$');
            END IF;
        END
        $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_incidents_tenant_service_opened "
        "ON incidents (tenant_id, service, opened_at, id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_incidents_tenant_service_opened")
    op.execute("ALTER TABLE incidents DROP CONSTRAINT IF EXISTS ck_incidents_service")
    op.execute("ALTER TABLE incidents DROP COLUMN IF EXISTS service")
