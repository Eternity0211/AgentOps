import { consoleConfig } from "./config";

export const approvalStatuses = [
  "PENDING",
  "APPROVED",
  "REJECTED",
  "EXPIRED",
] as const;

export type ApprovalStatus = (typeof approvalStatuses)[number];

export interface SeparationFeedback {
  required: boolean;
  satisfied: boolean;
  code: string;
  detail: string;
}

export interface ApprovalSummary {
  id: string;
  incidentId: string;
  proposalId: string;
  proposalVersion: number;
  proposalFingerprint: string;
  policyDecisionFingerprint: string;
  proposerActorId: string;
  riskLevel: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  status: ApprovalStatus;
  version: number;
  requestedAt: string;
  expiresAt: string;
  decidedAt: string | null;
  decidedBy: string | null;
  decisionReason: string | null;
  expired: boolean;
  invalidated: boolean;
  separationOfDuties: SeparationFeedback;
  schemaVersion: string;
}

export interface PolicyReason {
  code: string;
  detail: string;
}

export interface ApprovalPolicy {
  decisionId: string;
  policyVersion: string;
  outcome: string;
  riskLevel: ApprovalSummary["riskLevel"];
  reasons: PolicyReason[];
  environment: string;
  blastRadius: string;
  maintenanceWindow: string;
  service: string;
  requesterRoles: string[];
  separationOfDutiesRequired: boolean;
  evaluatedAt: string;
  approvalTtlSeconds: number;
  inputFingerprint: string;
  decisionFingerprint: string;
  schemaVersion: string;
}

export interface ProposalDiffEntry {
  path: string;
  before: unknown;
  after: unknown;
}

export interface ApprovalDetail {
  approval: ApprovalSummary;
  proposal: Record<string, unknown>;
  policy: ApprovalPolicy;
  reviewFingerprint: string;
  replacementProposal: Record<string, unknown> | null;
  proposalDiff: ProposalDiffEntry[];
  invalidation: {
    invalidatedBy: string;
    invalidatedAt: string;
    replacementProposalId: string;
    replacementProposalVersion: number;
    replacementProposalFingerprint: string;
    schemaVersion: string;
  } | null;
}

export interface ApprovalPage {
  items: ApprovalSummary[];
  nextCursor: string | null;
}

export class ApprovalRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly requestId: string | null,
  ) {
    super(detail);
    this.name = "ApprovalRequestError";
  }
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`invalid ${label} response`);
  }
  return value as Record<string, unknown>;
}

function identifier(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 128;
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(Date.parse(value));
}

function nullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function fingerprint(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function parseSeparation(value: unknown): SeparationFeedback {
  const row = record(value, "separation-of-duties");
  if (
    typeof row.required !== "boolean" ||
    typeof row.satisfied !== "boolean" ||
    !identifier(row.code) ||
    typeof row.detail !== "string" ||
    row.detail.length === 0 ||
    row.detail.length > 512
  ) {
    throw new Error("invalid separation-of-duties response");
  }
  return {
    required: row.required,
    satisfied: row.satisfied,
    code: row.code,
    detail: row.detail,
  };
}

export function parseApprovalSummary(value: unknown): ApprovalSummary {
  const row = record(value, "Approval");
  const riskLevels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;
  if (
    !identifier(row.id) ||
    !identifier(row.incident_id) ||
    !identifier(row.proposal_id) ||
    !Number.isInteger(row.proposal_version) ||
    (row.proposal_version as number) < 1 ||
    !fingerprint(row.proposal_fingerprint) ||
    !fingerprint(row.policy_decision_fingerprint) ||
    !identifier(row.proposer_actor_id) ||
    !riskLevels.includes(row.risk_level as ApprovalSummary["riskLevel"]) ||
    !approvalStatuses.includes(row.status as ApprovalStatus) ||
    !Number.isInteger(row.version) ||
    (row.version as number) < 1 ||
    !timestamp(row.requested_at) ||
    !timestamp(row.expires_at) ||
    !nullableString(row.decided_at) ||
    (row.decided_at !== null && !timestamp(row.decided_at)) ||
    !nullableString(row.decided_by) ||
    !nullableString(row.decision_reason) ||
    typeof row.expired !== "boolean" ||
    typeof row.invalidated !== "boolean" ||
    !identifier(row.schema_version)
  ) {
    throw new Error("invalid Approval response");
  }
  return {
    id: row.id,
    incidentId: row.incident_id,
    proposalId: row.proposal_id,
    proposalVersion: row.proposal_version as number,
    proposalFingerprint: row.proposal_fingerprint,
    policyDecisionFingerprint: row.policy_decision_fingerprint,
    proposerActorId: row.proposer_actor_id,
    riskLevel: row.risk_level as ApprovalSummary["riskLevel"],
    status: row.status as ApprovalStatus,
    version: row.version as number,
    requestedAt: row.requested_at,
    expiresAt: row.expires_at,
    decidedAt: row.decided_at,
    decidedBy: row.decided_by,
    decisionReason: row.decision_reason,
    expired: row.expired,
    invalidated: row.invalidated,
    separationOfDuties: parseSeparation(row.separation_of_duties),
    schemaVersion: row.schema_version,
  };
}

function parsePolicy(value: unknown): ApprovalPolicy {
  const row = record(value, "Approval policy");
  const riskLevels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;
  if (
    !identifier(row.decision_id) ||
    !identifier(row.policy_version) ||
    !identifier(row.outcome) ||
    !riskLevels.includes(row.risk_level as ApprovalSummary["riskLevel"]) ||
    !Array.isArray(row.reasons) ||
    !identifier(row.environment) ||
    !identifier(row.blast_radius) ||
    !identifier(row.maintenance_window) ||
    !identifier(row.service) ||
    !Array.isArray(row.requester_roles) ||
    !row.requester_roles.every(identifier) ||
    typeof row.separation_of_duties_required !== "boolean" ||
    !timestamp(row.evaluated_at) ||
    !Number.isInteger(row.approval_ttl_seconds) ||
    (row.approval_ttl_seconds as number) < 60 ||
    !fingerprint(row.input_fingerprint) ||
    !fingerprint(row.decision_fingerprint) ||
    !identifier(row.schema_version)
  ) {
    throw new Error("invalid Approval policy response");
  }
  const reasons = row.reasons.map((value) => {
    const reason = record(value, "Policy reason");
    if (!identifier(reason.code) || typeof reason.detail !== "string") {
      throw new Error("invalid Policy reason response");
    }
    return { code: reason.code, detail: reason.detail };
  });
  return {
    decisionId: row.decision_id,
    policyVersion: row.policy_version,
    outcome: row.outcome,
    riskLevel: row.risk_level as ApprovalSummary["riskLevel"],
    reasons,
    environment: row.environment,
    blastRadius: row.blast_radius,
    maintenanceWindow: row.maintenance_window,
    service: row.service,
    requesterRoles: row.requester_roles,
    separationOfDutiesRequired: row.separation_of_duties_required,
    evaluatedAt: row.evaluated_at,
    approvalTtlSeconds: row.approval_ttl_seconds as number,
    inputFingerprint: row.input_fingerprint,
    decisionFingerprint: row.decision_fingerprint,
    schemaVersion: row.schema_version,
  };
}

export function parseApprovalDetail(value: unknown): ApprovalDetail {
  const row = record(value, "Approval detail");
  const proposal = record(row.proposal, "proposal");
  const parameters = record(proposal.parameters, "proposal parameters");
  const prerequisites = record(
    proposal.prerequisites,
    "proposal prerequisites",
  );
  const verification = record(
    proposal.verification_conditions,
    "proposal verification conditions",
  );
  const failure = record(
    proposal.failure_handling,
    "proposal failure handling",
  );
  const replacementProposal =
    row.replacement_proposal === null
      ? null
      : record(row.replacement_proposal, "replacement proposal");
  if (
    !fingerprint(row.review_fingerprint) ||
    !Array.isArray(row.proposal_diff) ||
    !identifier(proposal.proposal_id) ||
    !Number.isInteger(proposal.proposal_version) ||
    proposal.action !== "rollback_service" ||
    !identifier(parameters.service) ||
    !identifier(parameters.introducing_deployment_evidence_id) ||
    !identifier(prerequisites.current_version_evidence_id) ||
    !Number.isInteger(verification.max_error_rate_basis_points) ||
    !Number.isInteger(verification.max_p95_latency_ms) ||
    !Number.isInteger(verification.stability_window_seconds) ||
    !identifier(failure.route) ||
    !Number.isInteger(failure.max_rediagnosis_attempts) ||
    !Array.isArray(proposal.risk_assumptions) ||
    proposal.risk_assumptions.length === 0 ||
    !proposal.risk_assumptions.every(
      (item) => typeof item === "string" && item.length > 0,
    )
  ) {
    throw new Error("invalid Approval detail response");
  }
  const proposalDiff = row.proposal_diff.map((value) => {
    const item = record(value, "proposal diff");
    if (typeof item.path !== "string" || !item.path.startsWith("$.")) {
      throw new Error("invalid proposal diff response");
    }
    return { path: item.path, before: item.before, after: item.after };
  });
  let invalidation: ApprovalDetail["invalidation"] = null;
  if (row.invalidation !== null) {
    const item = record(row.invalidation, "Approval invalidation");
    if (
      !identifier(item.invalidated_by) ||
      !timestamp(item.invalidated_at) ||
      !identifier(item.replacement_proposal_id) ||
      !Number.isInteger(item.replacement_proposal_version) ||
      !fingerprint(item.replacement_proposal_fingerprint) ||
      !identifier(item.schema_version)
    ) {
      throw new Error("invalid Approval invalidation response");
    }
    invalidation = {
      invalidatedBy: item.invalidated_by,
      invalidatedAt: item.invalidated_at,
      replacementProposalId: item.replacement_proposal_id,
      replacementProposalVersion: item.replacement_proposal_version as number,
      replacementProposalFingerprint: item.replacement_proposal_fingerprint,
      schemaVersion: item.schema_version,
    };
  }
  if ((replacementProposal === null) !== (invalidation === null)) {
    throw new Error("invalid Approval revision response");
  }
  return {
    approval: parseApprovalSummary(row.approval),
    proposal,
    policy: parsePolicy(row.policy),
    reviewFingerprint: row.review_fingerprint,
    replacementProposal,
    proposalDiff,
    invalidation,
  };
}

async function body(response: Response, label: string): Promise<unknown> {
  if (response.ok) return response.json() as Promise<unknown>;
  let detail = `${label} request failed (${response.status})`;
  try {
    const problem = record(await response.json(), "problem");
    if (typeof problem.detail === "string") detail = problem.detail;
  } catch {
    // Keep the bounded status-only fallback.
  }
  throw new ApprovalRequestError(
    response.status,
    detail,
    response.headers.get("X-Request-ID"),
  );
}

export async function loadApprovals(
  status?: string,
  cursor?: string,
  signal?: AbortSignal,
): Promise<ApprovalPage> {
  const query = new URLSearchParams({ limit: "20" });
  if (status) query.set("status", status);
  if (cursor) query.set("cursor", cursor);
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/approvals?${query}`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  const page = record(await body(response, "Approval list"), "Approval page");
  if (
    !Array.isArray(page.items) ||
    !(typeof page.next_cursor === "string" || page.next_cursor === null)
  ) {
    throw new Error("invalid Approval page response");
  }
  return {
    items: page.items.map(parseApprovalSummary),
    nextCursor: page.next_cursor,
  };
}

export async function loadApproval(
  approvalId: string,
  signal?: AbortSignal,
): Promise<ApprovalDetail> {
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/approvals/${encodeURIComponent(approvalId)}`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  return parseApprovalDetail(await body(response, "Approval detail"));
}

export async function decideApproval(
  approvalId: string,
  operation: "approve" | "reject",
  expectedVersion: number,
  reason: string,
): Promise<ApprovalSummary> {
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/approvals/${encodeURIComponent(approvalId)}/${operation}`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        expected_version: expectedVersion,
        reason,
        correlation_id: crypto.randomUUID(),
        causation_id: `console-${operation}`,
      }),
    },
  );
  const result = record(
    await body(response, `Approval ${operation}`),
    "Approval decision",
  );
  return parseApprovalSummary(result.approval);
}
