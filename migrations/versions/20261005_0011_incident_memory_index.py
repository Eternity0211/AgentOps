"""Add authoritative Incident memory projections and vector binding.

Revision ID: 20261005_0011
Revises: 20261005_0010
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

from agentops_incident_commander.infrastructure.persistence.models import Base

revision: str = "20261005_0011"
down_revision: str | None = "20261005_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["incident_memory_projections"].create(bind=op.get_bind())
    op.execute(
        """
        CREATE FUNCTION enforce_incident_memory_embedding_source()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM incident_memory_projections p
                WHERE p.source_incident_id = NEW.incident_id
                  AND p.content_fingerprint = NEW.source_content_hash
            ) THEN
                RAISE EXCEPTION USING
                    MESSAGE = 'embedding source is not an authoritative memory projection',
                    ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER incident_memory_embedding_source_guard "
        "BEFORE INSERT OR UPDATE ON incident_memory_embeddings "
        "FOR EACH ROW EXECUTE FUNCTION enforce_incident_memory_embedding_source()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER incident_memory_embedding_source_guard ON incident_memory_embeddings")
    op.execute("DROP FUNCTION enforce_incident_memory_embedding_source()")
    Base.metadata.tables["incident_memory_projections"].drop(bind=op.get_bind())
