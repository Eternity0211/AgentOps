"""SQLAlchemy mappings for the first operational aggregates."""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agentops_incident_commander.domain import (
    EvidenceGateOutcome,
    EvidenceSourceType,
    IncidentState,
    PromptInjectionStatus,
    TrustClassification,
)

_STATES = ", ".join(f"'{state.value}'" for state in IncidentState)
_SEVERITIES = "'SEV1', 'SEV2', 'SEV3', 'SEV4'"
_EVIDENCE_SOURCES = ", ".join(f"'{value.value}'" for value in EvidenceSourceType)
_EVIDENCE_TRUST = ", ".join(f"'{value.value}'" for value in TrustClassification)
_INJECTION_STATES = ", ".join(f"'{value.value}'" for value in PromptInjectionStatus)
_GATE_OUTCOMES = ", ".join(f"'{value.value}'" for value in EvidenceGateOutcome)


class Base(DeclarativeBase):
    """Metadata root for control-plane migrations."""


class AuditEventRow(Base):
    """Database-protected append-only audit ledger row."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("event_version >= 1", name="ck_audit_event_version"),
        CheckConstraint(
            "request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_audit_request_hash",
        ),
        CheckConstraint(
            "result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'",
            name="ck_audit_result_hash",
        ),
        Index("ix_audit_correlation_sequence", "correlation_id", "sequence"),
        Index("ix_audit_tenant_sequence", "tenant_id", "sequence"),
        Index("ix_audit_target_sequence", "target_type", "target_id", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(128), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    result_hash: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEventRow(Base):
    """Transactional event intent with bounded delivery lease state."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("aggregate_version >= 1", name="ck_outbox_aggregate_version"),
        CheckConstraint("max_attempts >= 1", name="ck_outbox_max_attempts"),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_outbox_attempt_count",
        ),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="ck_outbox_payload_hash"),
        CheckConstraint("available_at >= occurred_at", name="ck_outbox_time_order"),
        CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_outbox_lease_pair",
        ),
        CheckConstraint(
            "published_at IS NULL OR "
            "(lease_owner IS NULL AND lease_expires_at IS NULL AND dead_lettered_at IS NULL)",
            name="ck_outbox_published_state",
        ),
        CheckConstraint(
            "dead_lettered_at IS NULL OR "
            "(published_at IS NULL AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND attempt_count = max_attempts)",
            name="ck_outbox_dead_letter_state",
        ),
        UniqueConstraint(
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            "topic",
            name="uq_outbox_aggregate_intent",
        ),
        Index(
            "ix_outbox_dispatch",
            "published_at",
            "dead_lettered_at",
            "available_at",
            "sequence",
        ),
        Index("ix_outbox_lease_expiry", "lease_expires_at"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(512))


class JobRow(Base):
    """Durable worker job with an exclusive expiring lease."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 0 AND 100", name="ck_jobs_priority"),
        CheckConstraint("max_attempts >= 1", name="ck_jobs_max_attempts"),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= max_attempts",
            name="ck_jobs_attempt_count",
        ),
        CheckConstraint("available_at >= created_at", name="ck_jobs_time_order"),
        CheckConstraint(
            "(status = 'LEASED' AND lease_owner IS NOT NULL AND leased_at IS NOT NULL "
            "AND heartbeat_at IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'LEASED' AND lease_owner IS NULL AND leased_at IS NULL "
            "AND heartbeat_at IS NULL AND lease_expires_at IS NULL)",
            name="ck_jobs_lease_state",
        ),
        CheckConstraint(
            "(status IN ('COMPLETED', 'DEAD_LETTER', 'NEEDS_HUMAN')) = (terminal_at IS NOT NULL)",
            name="ck_jobs_terminal_state",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'LEASED', 'COMPLETED', 'DEAD_LETTER', 'NEEDS_HUMAN')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "failure_route IN ('DEAD_LETTER', 'NEEDS_HUMAN')",
            name="ck_jobs_failure_route",
        ),
        Index("ix_jobs_claim", "status", "available_at", "priority", "sequence"),
        Index("ix_jobs_lease_expiry", "lease_expires_at"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_route: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(512))


class IncidentRow(Base):
    """Mutable Incident aggregate guarded by an optimistic version."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(f"severity IN ({_SEVERITIES})", name="ck_incidents_severity"),
        CheckConstraint(f"state IN ({_STATES})", name="ck_incidents_state"),
        UniqueConstraint("id", "tenant_id", name="uq_incidents_id_tenant"),
        CheckConstraint("version >= 1", name="ck_incidents_version_positive"),
        CheckConstraint("updated_at >= opened_at", name="ck_incidents_time_order"),
        CheckConstraint(
            "(state = 'CLOSED') = (closed_at IS NOT NULL)",
            name="ck_incidents_closed_timestamp",
        ),
        Index("ix_incidents_tenant_opened", "tenant_id", "opened_at", "id"),
        CheckConstraint(
            "(state = 'CANCELLED') = (cancelled_at IS NOT NULL)",
            name="ck_incidents_cancelled_timestamp",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(4), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceRow(Base):
    """Immutable incident-owned Evidence metadata resolving an external Artifact."""

    __tablename__ = "evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "tenant_id"],
            ["incidents.id", "incidents.tenant_id"],
            ondelete="RESTRICT",
            name="fk_evidence_incident_tenant",
        ),
        CheckConstraint(f"source_type IN ({_EVIDENCE_SOURCES})", name="ck_evidence_source"),
        CheckConstraint(f"trust IN ({_EVIDENCE_TRUST})", name="ck_evidence_trust"),
        CheckConstraint(
            f"prompt_injection_status IN ({_INJECTION_STATES})",
            name="ck_evidence_injection_status",
        ),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_evidence_content_hash"),
        CheckConstraint(
            "quality_score_basis_points BETWEEN 0 AND 10000", name="ck_evidence_quality"
        ),
        CheckConstraint("observed_to >= observed_from", name="ck_evidence_observation_order"),
        CheckConstraint("collected_at >= observed_to", name="ck_evidence_collection_order"),
        CheckConstraint("expires_at > collected_at", name="ck_evidence_expiry_order"),
        UniqueConstraint("artifact_id", name="uq_evidence_artifact"),
        Index("ix_evidence_incident_collected", "tenant_id", "incident_id", "collected_at"),
        Index("ix_evidence_expiry", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_instance: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_query: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_score_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    redaction_transform_id: Mapped[str | None] = mapped_column(String(128))
    parent_evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    trust: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_injection_status: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)


class EvidenceGateDecisionRow(Base):
    """Immutable, reproducible Evidence Gate input and decision snapshot."""

    __tablename__ = "evidence_gate_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "tenant_id"],
            ["incidents.id", "incidents.tenant_id"],
            ondelete="CASCADE",
            name="fk_gate_decisions_incident_tenant",
        ),
        CheckConstraint(f"outcome IN ({_GATE_OUTCOMES})", name="ck_gate_decisions_outcome"),
        CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_gate_decisions_input_fingerprint",
        ),
        CheckConstraint(
            "model_confidence_basis_points IS NULL OR "
            "model_confidence_basis_points BETWEEN 0 AND 10000",
            name="ck_gate_decisions_confidence",
        ),
        CheckConstraint(
            "jsonb_typeof(reasons) = 'array' AND "
            "((outcome = 'PASS' AND jsonb_array_length(reasons) = 0) OR "
            "(outcome = 'FAIL' AND jsonb_array_length(reasons) > 0))",
            name="ck_gate_decisions_reasons",
        ),
        CheckConstraint(
            "jsonb_typeof(evaluated_evidence_ids) = 'array'",
            name="ck_gate_decisions_evidence_ids",
        ),
        CheckConstraint(
            "jsonb_typeof(input_snapshot) = 'object'",
            name="ck_gate_decisions_input_snapshot",
        ),
        UniqueConstraint(
            "tenant_id",
            "incident_id",
            "candidate_id",
            "input_fingerprint",
            name="uq_gate_decisions_input",
        ),
        Index(
            "ix_gate_decisions_incident_time",
            "tenant_id",
            "incident_id",
            "evaluated_at",
            "sequence",
        ),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    reasons: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    evaluated_evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    rules_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_confidence_basis_points: Mapped[int | None] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)


class IdempotencyRecordRow(Base):
    """Durable result cache for one tenant/actor/control-command identity."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_idempotency_request_hash"),
        CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 200 AND 599",
            name="ck_idempotency_response_status",
        ),
        CheckConstraint(
            "(response_status IS NULL AND response_body IS NULL AND completed_at IS NULL) OR "
            "(response_status IS NOT NULL AND response_body IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="ck_idempotency_completion_state",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_idempotency_time_order",
        ),
        UniqueConstraint(
            "tenant_id",
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_command",
        ),
        Index("ix_idempotency_created", "created_at"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(256), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
