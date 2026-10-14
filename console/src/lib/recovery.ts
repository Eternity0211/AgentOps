import { consoleConfig } from "./config";

export type ExecutionStatus =
  "STARTED" | "SUCCEEDED" | "FAILED" | "TIMED_OUT" | "UNCERTAIN";

export interface RecoverySnapshot {
  artifactId: string;
  contentHash: string;
  deployedVersion: string;
  observedAt: string;
}

export interface RecoveryExecution {
  id: string;
  action: "rollback_service";
  approvalId: string;
  actorId: string;
  status: ExecutionStatus;
  version: number;
  service: string;
  environment: string;
  targetReference: string;
  expectedCurrentVersion: string;
  stableVersion: string;
  before: RecoverySnapshot;
  after: RecoverySnapshot | null;
  startedAt: string;
  completedAt: string | null;
  failureCode: string | null;
  proposalFingerprint: string;
  policyDecisionFingerprint: string;
  executionFingerprint: string;
  schemaVersion: string;
}

export interface VerificationSample {
  observedAt: string;
  errorRateBasisPoints: number;
  p95LatencyMs: number;
  healthEndpointHealthy: boolean;
  deployedVersion: string;
  newAlertCount: number;
}

export interface RecoveryVerification {
  id: string;
  observationId: string;
  scenario: string;
  outcome: "PASS" | "FAIL";
  reasons: string[];
  service: string;
  environment: string;
  expectedStableVersion: string;
  windowStartedAt: string;
  windowEndedAt: string;
  windowDurationSeconds: number;
  sampleCount: number;
  firstSample: VerificationSample;
  lastSample: VerificationSample;
  evidence: Readonly<{
    errorRate: string;
    p95Latency: string;
    healthEndpoint: string;
    deployedVersion: string;
    newAlerts: string;
  }>;
  collectedAt: string;
  expiresAt: string;
  evaluatedAt: string;
  criteriaFingerprint: string;
  observationFingerprint: string;
  executionFingerprint: string;
  inputFingerprint: string;
  decisionFingerprint: string;
  rulesVersion: string;
  schemaVersion: string;
}

export interface RecoveryRouteTransition {
  priorState: string;
  newState: string;
  priorVersion: number;
  newVersion: number;
  reason: string;
  actorId: string;
  correlationId: string;
  causationId: string;
  occurredAt: string;
}

export interface RecoveryRoute {
  status: "PENDING" | "CLOSED" | "REDIAGNOSE" | "NEEDS_HUMAN" | "CANCELLED";
  finalState: string | null;
  transitions: RecoveryRouteTransition[];
}

export interface RecoveryResult {
  execution: RecoveryExecution | null;
  verification: RecoveryVerification | null;
  route: RecoveryRoute | null;
  compensation: Readonly<{
    eligible: false;
    separatelyAuthorized: false;
    status: "FORBIDDEN_FOR_ROLLBACK_SERVICE";
    detail: string;
  }>;
}

const SHA256 = /^[a-f0-9]{64}$/;
const EXECUTION_STATUSES: ExecutionStatus[] = [
  "STARTED",
  "SUCCEEDED",
  "FAILED",
  "TIMED_OUT",
  "UNCERTAIN",
];
const ROUTE_STATUSES: RecoveryRoute["status"][] = [
  "PENDING",
  "CLOSED",
  "REDIAGNOSE",
  "NEEDS_HUMAN",
  "CANCELLED",
];

function invalid(): never {
  throw new Error("invalid recovery response");
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return invalid();
  return value as Record<string, unknown>;
}

function string(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) return invalid();
  return value;
}

function instant(value: unknown): string {
  const result = string(value);
  if (!Number.isFinite(Date.parse(result))) return invalid();
  return result;
}

function integer(
  value: unknown,
  minimum = 0,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (
    !Number.isInteger(value) ||
    (value as number) < minimum ||
    (value as number) > maximum
  ) {
    return invalid();
  }
  return value as number;
}

function hash(value: unknown): string {
  const result = string(value);
  if (!SHA256.test(result)) return invalid();
  return result;
}

function snapshot(value: unknown): RecoverySnapshot {
  const row = record(value);
  return {
    artifactId: string(row.artifact_id),
    contentHash: hash(row.content_hash),
    deployedVersion: string(row.deployed_version),
    observedAt: instant(row.observed_at),
  };
}

function execution(value: unknown): RecoveryExecution {
  const row = record(value);
  const status = string(row.status);
  if (
    !EXECUTION_STATUSES.includes(status as ExecutionStatus) ||
    row.action !== "rollback_service"
  ) {
    return invalid();
  }
  const startedAt = instant(row.started_at);
  const completedAt =
    row.completed_at === null ? null : instant(row.completed_at);
  const before = snapshot(row.before);
  const after = row.after === null ? null : snapshot(row.after);
  const failureCode =
    row.failure_code === null ? null : string(row.failure_code);
  const target: RecoveryExecution = {
    id: string(row.id),
    action: "rollback_service",
    approvalId: string(row.approval_id),
    actorId: string(row.actor_id),
    status: status as ExecutionStatus,
    version: integer(row.version, 1),
    service: string(row.service),
    environment: string(row.environment),
    targetReference: string(row.target_reference),
    expectedCurrentVersion: string(row.expected_current_version),
    stableVersion: string(row.stable_version),
    before,
    after,
    startedAt,
    completedAt,
    failureCode,
    proposalFingerprint: hash(row.proposal_fingerprint),
    policyDecisionFingerprint: hash(row.policy_decision_fingerprint),
    executionFingerprint: hash(row.execution_fingerprint),
    schemaVersion: string(row.schema_version),
  };
  const terminal = status !== "STARTED";
  if (
    before.deployedVersion !== target.expectedCurrentVersion ||
    Date.parse(before.observedAt) > Date.parse(startedAt) ||
    terminal !== (completedAt !== null) ||
    (completedAt !== null && Date.parse(completedAt) < Date.parse(startedAt)) ||
    (status === "SUCCEEDED" &&
      (after === null ||
        after.deployedVersion !== target.stableVersion ||
        failureCode !== null)) ||
    (status !== "SUCCEEDED" && terminal && failureCode === null) ||
    (!terminal && (after !== null || failureCode !== null))
  ) {
    return invalid();
  }
  return target;
}

function sample(value: unknown): VerificationSample {
  const row = record(value);
  if (typeof row.health_endpoint_healthy !== "boolean") return invalid();
  return {
    observedAt: instant(row.observed_at),
    errorRateBasisPoints: integer(row.error_rate_basis_points, 0, 10_000),
    p95LatencyMs: integer(row.p95_latency_ms, 0, 300_000),
    healthEndpointHealthy: row.health_endpoint_healthy,
    deployedVersion: string(row.deployed_version),
    newAlertCount: integer(row.new_alert_count, 0, 10_000),
  };
}

function verification(
  value: unknown,
  current: RecoveryExecution,
): RecoveryVerification {
  const row = record(value);
  const outcome = string(row.outcome);
  if (outcome !== "PASS" && outcome !== "FAIL") return invalid();
  if (!Array.isArray(row.reasons)) return invalid();
  const reasons = row.reasons.map(string);
  const windowStartedAt = instant(row.window_started_at);
  const windowEndedAt = instant(row.window_ended_at);
  const firstSample = sample(row.first_sample);
  const lastSample = sample(row.last_sample);
  const evidenceRow = record(row.evidence);
  const evidence = {
    errorRate: string(evidenceRow.error_rate),
    p95Latency: string(evidenceRow.p95_latency),
    healthEndpoint: string(evidenceRow.health_endpoint),
    deployedVersion: string(evidenceRow.deployed_version),
    newAlerts: string(evidenceRow.new_alerts),
  };
  const result: RecoveryVerification = {
    id: string(row.id),
    observationId: string(row.observation_id),
    scenario: string(row.scenario),
    outcome,
    reasons,
    service: string(row.service),
    environment: string(row.environment),
    expectedStableVersion: string(row.expected_stable_version),
    windowStartedAt,
    windowEndedAt,
    windowDurationSeconds: integer(row.window_duration_seconds, 1, 3_600),
    sampleCount: integer(row.sample_count, 2, 512),
    firstSample,
    lastSample,
    evidence,
    collectedAt: instant(row.collected_at),
    expiresAt: instant(row.expires_at),
    evaluatedAt: instant(row.evaluated_at),
    criteriaFingerprint: hash(row.criteria_fingerprint),
    observationFingerprint: hash(row.observation_fingerprint),
    executionFingerprint: hash(row.execution_fingerprint),
    inputFingerprint: hash(row.input_fingerprint),
    decisionFingerprint: hash(row.decision_fingerprint),
    rulesVersion: string(row.rules_version),
    schemaVersion: string(row.schema_version),
  };
  const duration =
    (Date.parse(windowEndedAt) - Date.parse(windowStartedAt)) / 1000;
  if (
    current.status !== "SUCCEEDED" ||
    result.service !== current.service ||
    result.environment !== current.environment ||
    result.expectedStableVersion !== current.stableVersion ||
    result.executionFingerprint !== current.executionFingerprint ||
    duration !== result.windowDurationSeconds ||
    firstSample.observedAt !== windowStartedAt ||
    lastSample.observedAt !== windowEndedAt ||
    (outcome === "PASS") !== (reasons.length === 0) ||
    new Set(reasons).size !== reasons.length ||
    new Set(Object.values(evidence)).size !== 5 ||
    Date.parse(windowEndedAt) > Date.parse(result.collectedAt) ||
    Date.parse(result.collectedAt) >= Date.parse(result.expiresAt) ||
    Date.parse(result.evaluatedAt) < Date.parse(result.collectedAt)
  ) {
    return invalid();
  }
  return result;
}

function route(value: unknown, result: RecoveryVerification): RecoveryRoute {
  const row = record(value);
  const status = string(row.status);
  if (
    !ROUTE_STATUSES.includes(status as RecoveryRoute["status"]) ||
    !Array.isArray(row.transitions)
  ) {
    return invalid();
  }
  const transitions = row.transitions.map((item) => {
    const transition = record(item);
    const parsed: RecoveryRouteTransition = {
      priorState: string(transition.prior_state),
      newState: string(transition.new_state),
      priorVersion: integer(transition.prior_version, 1),
      newVersion: integer(transition.new_version, 2),
      reason: string(transition.reason),
      actorId: string(transition.actor_id),
      correlationId: string(transition.correlation_id),
      causationId: string(transition.causation_id),
      occurredAt: instant(transition.occurred_at),
    };
    if (
      parsed.newVersion !== parsed.priorVersion + 1 ||
      parsed.causationId !== result.id ||
      Date.parse(parsed.occurredAt) < Date.parse(result.evaluatedAt)
    )
      return invalid();
    return parsed;
  });
  const finalState = row.final_state === null ? null : string(row.final_state);
  if (
    (status === "PENDING" &&
      (transitions.length !== 0 || finalState !== null)) ||
    (status !== "PENDING" &&
      (transitions.length === 0 ||
        finalState !== transitions.at(-1)?.newState)) ||
    transitions.some(
      (item, index) =>
        index > 0 && item.priorVersion !== transitions[index - 1]!.newVersion,
    )
  )
    return invalid();
  return { status: status as RecoveryRoute["status"], finalState, transitions };
}

export function parseRecovery(value: unknown): RecoveryResult {
  const row = record(value);
  const compensation = record(row.compensation);
  if (
    compensation.eligible !== false ||
    compensation.separately_authorized !== false ||
    compensation.status !== "FORBIDDEN_FOR_ROLLBACK_SERVICE"
  )
    return invalid();
  const parsedCompensation = {
    eligible: false as const,
    separatelyAuthorized: false as const,
    status: "FORBIDDEN_FOR_ROLLBACK_SERVICE" as const,
    detail: string(compensation.detail),
  };
  if (row.execution === null) {
    if (row.verification !== null || row.route !== null) return invalid();
    return {
      execution: null,
      verification: null,
      route: null,
      compensation: parsedCompensation,
    };
  }
  const parsedExecution = execution(row.execution);
  if (row.verification === null) {
    if (row.route !== null) return invalid();
    return {
      execution: parsedExecution,
      verification: null,
      route: null,
      compensation: parsedCompensation,
    };
  }
  const parsedVerification = verification(row.verification, parsedExecution);
  if (row.route === null) return invalid();
  return {
    execution: parsedExecution,
    verification: parsedVerification,
    route: route(row.route, parsedVerification),
    compensation: parsedCompensation,
  };
}

export async function loadRecovery(
  incidentId: string,
  signal?: AbortSignal,
): Promise<RecoveryResult> {
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents/${encodeURIComponent(incidentId)}/recovery`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  if (!response.ok)
    throw new Error(`Recovery request failed (${response.status})`);
  return parseRecovery(await response.json());
}
