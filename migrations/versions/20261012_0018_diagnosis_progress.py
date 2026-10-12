"""Add the bounded Diagnosis progress read projection.

Revision ID: 20261012_0018
Revises: 20261011_0017
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261012_0018"
down_revision: str | None = "20261011_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE diagnosis_progress (
            workflow_run_id VARCHAR(128) PRIMARY KEY,
            tenant_id VARCHAR(128) NOT NULL,
            incident_id VARCHAR(128) NOT NULL,
            schema_version VARCHAR(64) NOT NULL,
            graph_version VARCHAR(64) NOT NULL,
            phase VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            checkpoint_sequence INTEGER NOT NULL,
            snapshot JSONB NOT NULL,
            snapshot_fingerprint VARCHAR(64) NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT fk_diagnosis_progress_incident_tenant
                FOREIGN KEY (incident_id, tenant_id)
                REFERENCES incidents (id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT ck_diagnosis_progress_phase CHECK (
                phase IN (
                    'CONTEXT_LOADING', 'PLANNING', 'INVESTIGATING', 'HYPOTHESIS',
                    'EVIDENCE_REVIEW', 'HUMAN_HANDOFF', 'CANCELLED', 'COMPLETE'
                )
            ),
            CONSTRAINT ck_diagnosis_progress_status CHECK (
                status IN ('ACTIVE', 'FAILED', 'COMPLETE', 'HUMAN_HANDOFF', 'CANCELLED')
            ),
            CONSTRAINT ck_diagnosis_progress_sequence CHECK (checkpoint_sequence >= 0),
            CONSTRAINT ck_diagnosis_progress_snapshot_object CHECK (
                jsonb_typeof(snapshot) = 'object'
            ),
            CONSTRAINT ck_diagnosis_progress_fingerprint CHECK (
                snapshot_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT uq_diagnosis_progress_scope UNIQUE (
                tenant_id, incident_id, workflow_run_id
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_diagnosis_progress_incident_time
        ON diagnosis_progress (
            tenant_id, incident_id, updated_at DESC, workflow_run_id DESC
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE diagnosis_progress")
