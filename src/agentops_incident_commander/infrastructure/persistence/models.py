"""SQLAlchemy mappings for the first operational aggregates."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agentops_incident_commander.domain import IncidentState

_STATES = ", ".join(f"'{state.value}'" for state in IncidentState)
_SEVERITIES = "'SEV1', 'SEV2', 'SEV3', 'SEV4'"


class Base(DeclarativeBase):
    """Metadata root for control-plane migrations."""


class IncidentRow(Base):
    """Mutable Incident aggregate guarded by an optimistic version."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(f"severity IN ({_SEVERITIES})", name="ck_incidents_severity"),
        CheckConstraint(f"state IN ({_STATES})", name="ck_incidents_state"),
        CheckConstraint("version >= 1", name="ck_incidents_version_positive"),
        CheckConstraint("updated_at >= opened_at", name="ck_incidents_time_order"),
        CheckConstraint(
            "(state = 'CLOSED') = (closed_at IS NOT NULL)",
            name="ck_incidents_closed_timestamp",
        ),
        CheckConstraint(
            "(state = 'CANCELLED') = (cancelled_at IS NOT NULL)",
            name="ck_incidents_cancelled_timestamp",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    severity: Mapped[str] = mapped_column(String(4), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncidentTransitionRow(Base):
    """Append-only state transition record."""

    __tablename__ = "incident_transitions"
    __table_args__ = (
        CheckConstraint(f"prior_state IN ({_STATES})", name="ck_transitions_prior_state"),
        CheckConstraint(f"new_state IN ({_STATES})", name="ck_transitions_new_state"),
        CheckConstraint("new_version = prior_version + 1", name="ck_transitions_version_step"),
        CheckConstraint("prior_state <> new_state", name="ck_transitions_state_changed"),
        UniqueConstraint("incident_id", "new_version", name="uq_transitions_incident_version"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    prior_state: Mapped[str] = mapped_column(String(32), nullable=False)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    prior_version: Mapped[int] = mapped_column(Integer, nullable=False)
    new_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IncidentCancellationRequestRow(Base):
    """Append-only record of immediate and deferred cancellation requests."""

    __tablename__ = "incident_cancellation_requests"
    __table_args__ = (
        CheckConstraint(f"state_when_requested IN ({_STATES})", name="ck_cancel_state"),
        CheckConstraint("new_version = prior_version + 1", name="ck_cancel_version_step"),
        CheckConstraint("disposition IN ('CANCELLED', 'DEFERRED')", name="ck_cancel_disposition"),
        UniqueConstraint("incident_id", "new_version", name="uq_cancel_incident_version"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    state_when_requested: Mapped[str] = mapped_column(String(32), nullable=False)
    prior_version: Mapped[int] = mapped_column(Integer, nullable=False)
    new_version: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AlertGroupRow(Base):
    """Time-bounded deduplication aggregate optionally attached to an Incident."""

    __tablename__ = "alert_groups"
    __table_args__ = (
        CheckConstraint(f"severity IN ({_SEVERITIES})", name="ck_alert_groups_severity"),
        CheckConstraint("length(fingerprint) = 64", name="ck_alert_groups_fingerprint_length"),
        CheckConstraint("occurrence_count >= 1", name="ck_alert_groups_occurrence_positive"),
        CheckConstraint("version >= 1", name="ck_alert_groups_version_positive"),
        CheckConstraint(
            "first_observed_at <= last_observed_at", name="ck_alert_groups_observation_order"
        ),
        CheckConstraint(
            "first_received_at <= last_received_at", name="ck_alert_groups_receipt_order"
        ),
        Index("ix_alert_groups_fingerprint_window", "fingerprint", "last_observed_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    incident_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("incidents.id", ondelete="RESTRICT")
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    rule: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(4), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class AlertRow(Base):
    """Immutable normalized Alert delivery associated with exactly one group."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(f"severity IN ({_SEVERITIES})", name="ck_alerts_severity"),
        CheckConstraint("length(fingerprint) = 64", name="ck_alerts_fingerprint_length"),
        CheckConstraint("received_at >= observed_at", name="ck_alerts_time_order"),
        Index("ix_alerts_group_id", "group_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("alert_groups.id", ondelete="RESTRICT"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(128), nullable=False)
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    rule: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(4), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dimensions: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)


class IncidentMemoryEmbeddingRow(Base):
    """Versioned vector index metadata pointing back to an authoritative closed Incident."""

    __tablename__ = "incident_memory_embeddings"
    __table_args__ = (
        CheckConstraint("length(source_content_hash) = 64", name="ck_embeddings_source_hash"),
        CheckConstraint("dimensions > 0 AND dimensions <= 16000", name="ck_embeddings_dimensions"),
        CheckConstraint(
            "vector_dims(embedding) = dimensions", name="ck_embeddings_vector_dimensions"
        ),
        UniqueConstraint(
            "incident_id",
            "provider",
            "model",
            "model_version",
            "content_schema_version",
            "normalization_version",
            name="uq_embeddings_versioned_source",
        ),
        Index("ix_embeddings_incident_id", "incident_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    incident_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    content_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(), nullable=False)
    reindex_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
