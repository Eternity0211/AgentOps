"""Add versioned postmortems and append-only human revisions.

Revision ID: 20261009_0016
Revises: 20261008_0015
Create Date: 2026-10-09
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261009_0016"
down_revision: str | None = "20261008_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["postmortems"].create(bind=op.get_bind())
    Base.metadata.tables["postmortem_revisions"].create(bind=op.get_bind())
    op.execute(
        """
        CREATE FUNCTION reject_postmortem_revision_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'postmortem_revisions is append-only; % is forbidden', TG_OP
                USING ERRCODE = '55000';
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER postmortem_revisions_reject_row_mutation
        BEFORE UPDATE OR DELETE ON postmortem_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_postmortem_revision_mutation()
        """
    )
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON postmortem_revisions FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP TRIGGER postmortem_revisions_reject_row_mutation ON postmortem_revisions")
    Base.metadata.tables["postmortem_revisions"].drop(bind=op.get_bind())
    Base.metadata.tables["postmortems"].drop(bind=op.get_bind())
    op.execute("DROP FUNCTION reject_postmortem_revision_mutation()")
