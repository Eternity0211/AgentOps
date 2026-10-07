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
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agentops_incident_commander.domain import (
    ACTION_EXECUTION_SCHEMA_VERSION,
    APPROVAL_INVALIDATION_SCHEMA_VERSION,
    APPROVAL_SCHEMA_VERSION,
    INCIDENT_MEMORY_SCHEMA_VERSION,
    MAX_PROMPT_CONTENT_BYTES,
    ActionExecutionStatus,
    ApprovalStatus,
    EvidenceGateOutcome,
    EvidenceSourceType,
    IncidentMemoryConfirmationSource,
    IncidentMemoryOutcome,
    IncidentState,
    ModelCallStatus,
    ModelCostSource,
    ModelMeteringUnavailableReason,
    PromptInjectionStatus,
    PromptLifecycleStatus,
    PromptPurpose,
    RiskLevel,
    TrustClassification,
)

_STATES = ", ".join(f"'{state.value}'" for state in IncidentState)
_SEVERITIES = "'SEV1', 'SEV2', 'SEV3', 'SEV4'"
_EVIDENCE_SOURCES = ", ".join(f"'{value.value}'" for value in EvidenceSourceType)
_EVIDENCE_TRUST = ", ".join(f"'{value.value}'" for value in TrustClassification)
_INJECTION_STATES = ", ".join(f"'{value.value}'" for value in PromptInjectionStatus)
_GATE_OUTCOMES = ", ".join(f"'{value.value}'" for value in EvidenceGateOutcome)
_PROMPT_PURPOSES = ", ".join(f"'{value.value}'" for value in PromptPurpose)
_PROMPT_STATUSES = ", ".join(f"'{value.value}'" for value in PromptLifecycleStatus)
_MODEL_CALL_STATUSES = ", ".join(f"'{value.value}'" for value in ModelCallStatus)
_MODEL_COST_SOURCES = ", ".join(f"'{value.value}'" for value in ModelCostSource)
_METERING_UNAVAILABLE = ", ".join(f"'{value.value}'" for value in ModelMeteringUnavailableReason)
_MEMORY_OUTCOMES = ", ".join(f"'{value.value}'" for value in IncidentMemoryOutcome)
_MEMORY_CONFIRMATIONS = ", ".join(f"'{value.value}'" for value in IncidentMemoryConfirmationSource)
_APPROVAL_STATUSES = ", ".join(f"'{value.value}'" for value in ApprovalStatus)
_RISK_LEVELS = ", ".join(f"'{value.value}'" for value in RiskLevel)
_ACTION_EXECUTION_STATUSES = ", ".join(f"'{value.value}'" for value in ActionExecutionStatus)


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


class PromptVersionRow(Base):
    """Tenant-scoped immutable Prompt content with mutable lifecycle status only."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        CheckConstraint(f"purpose IN ({_PROMPT_PURPOSES})", name="ck_prompt_purpose"),
        CheckConstraint(f"status IN ({_PROMPT_STATUSES})", name="ck_prompt_status"),
        CheckConstraint("content_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_prompt_hash"),
        UniqueConstraint("tenant_id", "prompt_id", "version", name="uq_prompt_version"),
        Index(
            "uq_prompt_active",
            "tenant_id",
            "prompt_id",
            unique=True,
            postgresql_where=sql_text("status = 'ACTIVE'"),
        ),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String(MAX_PROMPT_CONTENT_BYTES), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    model_parameters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_compatibility: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    trace: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rollback_predecessor: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)


class PromptLifecycleEventRow(Base):
    """Append-only Prompt lifecycle transition and regression snapshot."""

    __tablename__ = "prompt_lifecycle_events"
    __table_args__ = (
        UniqueConstraint("audit_event_id", name="uq_prompt_lifecycle_audit"),
        Index("ix_prompt_lifecycle_family", "tenant_id", "prompt_id", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_state: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    after_state: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    regression_evaluation: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    audit_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalRow(Base):
    """Mutable proposal-bound Approval aggregate with optimistic version."""

    __tablename__ = "approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "tenant_id"],
            ["incidents.id", "incidents.tenant_id"],
            name="fk_approvals_incident_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN ({_APPROVAL_STATUSES})", name="ck_approval_status"),
        CheckConstraint(f"risk_level IN ({_RISK_LEVELS})", name="ck_approval_risk"),
        CheckConstraint("version >= 1", name="ck_approval_version"),
        CheckConstraint("proposal_version >= 1", name="ck_approval_proposal_version"),
        CheckConstraint("expires_at > requested_at", name="ck_approval_expiry_order"),
        CheckConstraint(
            "proposal_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "policy_decision_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "policy_input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_approval_hashes",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL AND decided_by IS NULL "
            "AND decision_reason IS NULL) OR "
            "(status IN ('APPROVED', 'REJECTED') AND decided_at >= requested_at "
            "AND decided_at < expires_at AND decided_by IS NOT NULL "
            "AND decision_reason IS NOT NULL) OR "
            "(status = 'EXPIRED' AND decided_at >= expires_at AND decided_by IS NOT NULL "
            "AND decision_reason IS NOT NULL)",
            name="ck_approval_decision_state",
        ),
        UniqueConstraint(
            "tenant_id",
            "policy_decision_fingerprint",
            name="uq_approval_policy_decision",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_approval_id_tenant"),
        Index("ix_approval_incident_status", "tenant_id", "incident_id", "status"),
        Index("ix_approval_expiry", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision_id: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_decision_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    proposer_actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    independent_approver_required: Mapped[bool] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decision_reason: Mapped[str | None] = mapped_column(String(512))
    schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default=APPROVAL_SCHEMA_VERSION
    )


class ApprovalLifecycleEventRow(Base):
    """Append-only before/after record for each Approval transition."""

    __tablename__ = "approval_lifecycle_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["approval_id", "tenant_id"],
            ["approvals.id", "approvals.tenant_id"],
            name="fk_approval_events_approval_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("audit_event_id", name="uq_approval_lifecycle_audit"),
        Index("ix_approval_lifecycle", "tenant_id", "approval_id", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_state: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    after_state: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    audit_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalInvalidationRow(Base):
    """Immutable marker preventing reuse after a material proposal revision."""

    __tablename__ = "approval_invalidations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["approval_id", "tenant_id"],
            ["approvals.id", "approvals.tenant_id"],
            name="fk_approval_invalidations_approval_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "approval_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "prior_proposal_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "replacement_proposal_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "replacement_material_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_approval_invalidation_hashes",
        ),
        CheckConstraint(
            "replacement_proposal_version >= 1",
            name="ck_approval_invalidation_version",
        ),
        UniqueConstraint("audit_event_id", name="uq_approval_invalidation_audit"),
        Index("ix_approval_invalidation_incident", "tenant_id", "incident_id"),
    )

    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_proposal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    replacement_proposal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    replacement_proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    replacement_proposal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    replacement_material_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    invalidated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    invalidated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default=APPROVAL_INVALIDATION_SCHEMA_VERSION
    )


class ActionExecutionRow(Base):
    """Durable idempotent recovery execution with before/after Artifact references."""

    __tablename__ = "action_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "tenant_id"],
            ["incidents.id", "incidents.tenant_id"],
            name="fk_action_execution_incident_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["approval_id", "tenant_id"],
            ["approvals.id", "approvals.tenant_id"],
            name="fk_action_execution_approval_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"status IN ({_ACTION_EXECUTION_STATUSES})", name="ck_action_execution_status"
        ),
        CheckConstraint("version >= 1", name="ck_action_execution_version"),
        CheckConstraint(
            "proposal_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "policy_decision_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "request_fingerprint ~ '^[0-9a-f]{64}$' AND "
            "before_content_hash ~ '^[0-9a-f]{64}$' AND "
            "(after_content_hash IS NULL OR after_content_hash ~ '^[0-9a-f]{64}$')",
            name="ck_action_execution_hashes",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,127}$'",
            name="ck_action_execution_failure_code",
        ),
        CheckConstraint(
            "(after_artifact_id IS NULL AND after_content_hash IS NULL "
            "AND after_version IS NULL AND after_observed_at IS NULL) OR "
            "(after_artifact_id IS NOT NULL AND after_content_hash IS NOT NULL "
            "AND after_version IS NOT NULL AND after_observed_at IS NOT NULL)",
            name="ck_action_execution_after_snapshot",
        ),
        CheckConstraint(
            "(status = 'STARTED' AND completed_at IS NULL AND after_artifact_id IS NULL "
            "AND after_content_hash IS NULL AND after_version IS NULL "
            "AND after_observed_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'SUCCEEDED' AND completed_at >= started_at "
            "AND after_artifact_id IS NOT NULL AND after_content_hash IS NOT NULL "
            "AND after_version = stable_version AND after_observed_at BETWEEN started_at "
            "AND completed_at AND failure_code IS NULL) OR "
            "(status IN ('FAILED', 'TIMED_OUT', 'UNCERTAIN') AND completed_at >= started_at "
            "AND failure_code IS NOT NULL)",
            name="ck_action_execution_terminal_state",
        ),
        UniqueConstraint(
            "tenant_id",
            "actor_id",
            "incident_id",
            "idempotency_key",
            name="uq_action_execution_idempotency",
        ),
        UniqueConstraint("tenant_id", "approval_id", name="uq_action_execution_approval"),
        UniqueConstraint("id", "tenant_id", name="uq_action_execution_id_tenant"),
        Index("ix_action_execution_incident", "tenant_id", "incident_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposal_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    target_service: Mapped[str] = mapped_column(String(128), nullable=False)
    target_environment: Mapped[str] = mapped_column(String(32), nullable=False)
    target_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    expected_current_version: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_version: Mapped[str] = mapped_column(String(64), nullable=False)
    before_artifact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    before_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    before_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    after_artifact_id: Mapped[str | None] = mapped_column(String(128))
    after_content_hash: Mapped[str | None] = mapped_column(String(64))
    after_version: Mapped[str | None] = mapped_column(String(64))
    after_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default=ACTION_EXECUTION_SCHEMA_VERSION
    )


class ActionExecutionLockRow(Base):
    """One durable active execution owner for an exact backend target."""

    __tablename__ = "action_execution_locks"
    __table_args__ = (
        CheckConstraint(
            "target_key ~ '^[0-9a-f]{64}$'", name="ck_action_execution_lock_target_key"
        ),
    )

    target_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("action_executions.id", ondelete="RESTRICT"), unique=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    target_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActionExecutionEventRow(Base):
    """Append-only start/finish fingerprint history for a recovery action."""

    __tablename__ = "action_execution_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["execution_id", "tenant_id"],
            ["action_executions.id", "action_executions.tenant_id"],
            name="fk_action_execution_events_execution_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "before_fingerprint IS NULL OR before_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_action_execution_event_before_hash",
        ),
        CheckConstraint(
            "after_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_action_execution_event_after_hash",
        ),
        UniqueConstraint("audit_event_id", name="uq_action_execution_event_audit"),
        Index("ix_action_execution_events", "tenant_id", "execution_id", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_fingerprint: Mapped[str | None] = mapped_column(String(64))
    after_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelCallTraceRow(Base):
    """Content-free attempted model call and exact terminal metering metadata."""

    __tablename__ = "model_call_traces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "tenant_id"],
            ["incidents.id", "incidents.tenant_id"],
            name="fk_model_calls_incident_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "prompt_id", "prompt_version"],
            ["prompt_versions.tenant_id", "prompt_versions.prompt_id", "prompt_versions.version"],
            name="fk_model_calls_prompt_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"status IN ({_MODEL_CALL_STATUSES})", name="ck_model_calls_status"),
        CheckConstraint("attempt >= 1", name="ck_model_calls_attempt"),
        CheckConstraint(
            "prompt_fingerprint ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$' "
            "AND (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$')",
            name="ck_model_calls_hashes",
        ),
        CheckConstraint(
            "temperature_basis_points BETWEEN 0 AND 20000 "
            "AND top_p_basis_points BETWEEN 1 AND 10000 "
            "AND max_output_tokens BETWEEN 1 AND 32768",
            name="ck_model_calls_settings",
        ),
        CheckConstraint(
            "(status = 'STARTED' AND completed_at IS NULL AND response_hash IS NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'SUCCEEDED' AND completed_at >= started_at AND response_hash IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status IN ('FAILED', 'TIMED_OUT', 'REFUSED') AND completed_at >= started_at "
            "AND failure_code IS NOT NULL)",
            name="ck_model_calls_completion",
        ),
        CheckConstraint(
            "(status = 'STARTED' AND input_tokens IS NULL AND output_tokens IS NULL "
            "AND cached_input_tokens IS NULL AND reasoning_tokens IS NULL "
            "AND total_tokens IS NULL AND cost_nanounits IS NULL AND currency IS NULL "
            "AND cost_source IS NULL AND rate_card_version IS NULL "
            "AND metering_unavailable_reason IS NULL) OR "
            "(status <> 'STARTED' AND ((input_tokens >= 0 AND output_tokens >= 0 "
            "AND cached_input_tokens BETWEEN 0 AND input_tokens "
            "AND reasoning_tokens BETWEEN 0 AND output_tokens "
            "AND total_tokens = input_tokens + output_tokens AND cost_nanounits >= 0 "
            f"AND currency ~ '^[A-Z]{{3}}$' AND cost_source IN ({_MODEL_COST_SOURCES}) "
            "AND rate_card_version IS NOT NULL AND metering_unavailable_reason IS NULL) OR "
            "(input_tokens IS NULL AND output_tokens IS NULL AND cached_input_tokens IS NULL "
            "AND reasoning_tokens IS NULL AND total_tokens IS NULL AND cost_nanounits IS NULL "
            "AND currency IS NULL AND cost_source IS NULL AND rate_card_version IS NULL "
            f"AND metering_unavailable_reason IN ({_METERING_UNAVAILABLE}))))",
            name="ck_model_calls_metering",
        ),
        Index("ix_model_calls_incident_time", "tenant_id", "incident_id", "started_at", "id"),
        Index("ix_model_calls_workflow", "tenant_id", "workflow_run_id", "started_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    node: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    temperature_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    top_p_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer)
    input_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_hash: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cached_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cost_nanounits: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    cost_source: Mapped[str | None] = mapped_column(String(32))
    rate_card_version: Mapped[str | None] = mapped_column(String(64))
    metering_unavailable_reason: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(128))
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


class IncidentMemoryProjectionRow(Base):
    """Authoritative immutable projection admitted from one closed Incident."""

    __tablename__ = "incident_memory_projections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_incident_id", "tenant_id"],
            ["incidents.id", "incidents.tenant_id"],
            ondelete="RESTRICT",
            name="fk_memory_projection_incident_tenant",
        ),
        CheckConstraint("source_incident_state = 'CLOSED'", name="ck_memory_projection_closed"),
        CheckConstraint("source_incident_version >= 1", name="ck_memory_projection_version"),
        CheckConstraint(f"outcome IN ({_MEMORY_OUTCOMES})", name="ck_memory_projection_outcome"),
        CheckConstraint(
            f"confirmation_source IN ({_MEMORY_CONFIRMATIONS})",
            name="ck_memory_projection_confirmation",
        ),
        CheckConstraint(
            "(outcome = 'RECOVERED') = (recovery_action_reference IS NOT NULL)",
            name="ck_memory_projection_recovery_action",
        ),
        CheckConstraint("trust = 'HISTORICAL_REFERENCE'", name="ck_memory_projection_trust"),
        CheckConstraint(
            f"schema_version = '{INCIDENT_MEMORY_SCHEMA_VERSION}'",
            name="ck_memory_projection_schema",
        ),
        CheckConstraint("projected_at >= closed_at", name="ck_memory_projection_time_order"),
        CheckConstraint(
            "content_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_memory_projection_content_hash",
        ),
        CheckConstraint(
            "diagnosis_report_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_memory_projection_report_hash",
        ),
        CheckConstraint(
            "evidence_gate_decision_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_memory_projection_gate_hash",
        ),
        CheckConstraint(
            "jsonb_typeof(source_evidence_ids) = 'array' "
            "AND jsonb_array_length(source_evidence_ids) BETWEEN 1 AND 64",
            name="ck_memory_projection_evidence_count",
        ),
        UniqueConstraint("source_incident_id", name="uq_memory_projection_source_incident"),
        UniqueConstraint(
            "source_incident_id",
            "content_fingerprint",
            name="uq_memory_projection_source_content",
        ),
        Index("ix_memory_projection_tenant_service", "tenant_id", "service"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_incident_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_incident_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_incident_state: Mapped[str] = mapped_column(String(32), nullable=False)
    service: Mapped[str] = mapped_column(String(128), nullable=False)
    root_cause_summary: Mapped[str] = mapped_column(String(1024), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_summary: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    diagnosis_report_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_gate_decision_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_source: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmation_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    recovery_action_reference: Mapped[str | None] = mapped_column(String(128))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    trust: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)


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
