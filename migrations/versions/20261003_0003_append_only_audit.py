"""Add the database-protected append-only audit ledger.

Revision ID: 20261003_0003
Revises: 20261003_0002
Create Date: 2026-10-03
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261003_0003"
down_revision: str | None = "20261003_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create an insert-only ledger with defense-in-depth mutation denial."""
    Base.metadata.tables["audit_events"].create(bind=op.get_bind())
    op.execute(
        """
        CREATE FUNCTION reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only; % is forbidden', TG_OP
                USING ERRCODE = '55000';
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_reject_row_mutation
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_reject_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM PUBLIC")


def downgrade() -> None:
    """Remove ledger protections before removing the ledger itself."""
    op.execute("DROP TRIGGER audit_events_reject_truncate ON audit_events")
    op.execute("DROP TRIGGER audit_events_reject_row_mutation ON audit_events")
    Base.metadata.tables["audit_events"].drop(bind=op.get_bind())
    op.execute("DROP FUNCTION reject_audit_event_mutation()")
