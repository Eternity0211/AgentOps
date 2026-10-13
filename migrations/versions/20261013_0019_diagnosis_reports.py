"""Add immutable traced Diagnosis Agent reports.

Revision ID: 20261013_0019
Revises: 20261012_0018
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261013_0019"
down_revision: str | None = "20261012_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE diagnosis_reports (
            sequence BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(128) NOT NULL,
            incident_id VARCHAR(128) NOT NULL,
            workflow_run_id VARCHAR(128) NOT NULL,
            model_call_id VARCHAR(128) NOT NULL,
            disposition VARCHAR(32) NOT NULL,
            report JSONB NOT NULL,
            report_fingerprint VARCHAR(64) NOT NULL,
            produced_at TIMESTAMPTZ NOT NULL,
            schema_version VARCHAR(64) NOT NULL,
            CONSTRAINT fk_diagnosis_reports_incident_tenant
                FOREIGN KEY (incident_id, tenant_id)
                REFERENCES incidents (id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT fk_diagnosis_reports_model_call
                FOREIGN KEY (model_call_id)
                REFERENCES model_call_traces (id) ON DELETE RESTRICT,
            CONSTRAINT ck_diagnosis_reports_disposition CHECK (
                disposition IN (
                    'CANDIDATES', 'NEEDS_MORE_EVIDENCE', 'REFUSED', 'HUMAN_HANDOFF'
                )
            ),
            CONSTRAINT ck_diagnosis_reports_document CHECK (
                jsonb_typeof(report) = 'object'
            ),
            CONSTRAINT ck_diagnosis_reports_fingerprint CHECK (
                report_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT uq_diagnosis_reports_model_call UNIQUE (
                tenant_id, workflow_run_id, model_call_id
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_diagnosis_reports_incident_time
        ON diagnosis_reports (
            tenant_id, incident_id, produced_at DESC, sequence DESC
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE diagnosis_reports")
