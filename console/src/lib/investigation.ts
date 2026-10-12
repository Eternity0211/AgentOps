import { consoleConfig } from "./config";

export const investigationPhases = [
  "CONTEXT_LOADING",
  "PLANNING",
  "INVESTIGATING",
  "HYPOTHESIS",
  "EVIDENCE_REVIEW",
  "HUMAN_HANDOFF",
  "CANCELLED",
  "COMPLETE",
] as const;

export const investigationStatuses = [
  "ACTIVE",
  "FAILED",
  "COMPLETE",
  "HUMAN_HANDOFF",
  "CANCELLED",
] as const;

export const toolProgressStatuses = [
  "PLANNED",
  "RUNNING",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
] as const;

export interface BudgetCounter {
  used: number;
  maximum: number;
  remaining: number;
}

export interface InvestigationBudgets {
  steps: BudgetCounter;
  replans: BudgetCounter;
  toolCalls: BudgetCounter;
  modelCalls: BudgetCounter;
  tokens: BudgetCounter;
  costNanounits: BudgetCounter;
}

export interface InvestigationStepProgress {
  position: number;
  stepId: string;
  objective: string;
  expectedSource: string;
  dependsOn: string[];
  parallelGroup: number;
  toolCallId: string;
  toolName: string;
  toolVersion: string;
  status: (typeof toolProgressStatuses)[number];
  failureCode: string | null;
  startedAt: string | null;
  completedAt: string | null;
}

export interface InvestigationPlanProgress {
  attempt: number;
  planId: string;
  summary: string;
  modelCallId: string;
  createdAt: string;
  steps: InvestigationStepProgress[];
}

export interface ReplanProgress {
  completedAttempt: number;
  nextAttempt: number;
  decisionFingerprint: string;
  reasonCode: string;
  occurredAt: string;
}

export interface InvestigationProgress {
  schemaVersion: string;
  workflowRunId: string;
  graphVersion: string;
  phase: (typeof investigationPhases)[number];
  status: (typeof investigationStatuses)[number];
  budgets: InvestigationBudgets;
  plans: InvestigationPlanProgress[];
  replans: ReplanProgress[];
  checkpointSequence: number;
  errorCode: string | null;
  updatedAt: string;
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid investigation progress response");
  }
  return value as Record<string, unknown>;
}

function string(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("invalid investigation progress response");
  }
  return value;
}

function nullableString(value: unknown): string | null {
  if (value === null) return null;
  return string(value);
}

function integer(value: unknown): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error("invalid investigation progress response");
  }
  return value as number;
}

function parseBudget(value: unknown): BudgetCounter {
  const item = record(value);
  const used = integer(item.used);
  const maximum = integer(item.maximum);
  const remaining = integer(item.remaining);
  if (used > maximum || remaining !== maximum - used) {
    throw new Error("invalid investigation progress response");
  }
  return { used, maximum, remaining };
}

function parseStep(value: unknown): InvestigationStepProgress {
  const item = record(value);
  if (!Array.isArray(item.depends_on)) {
    throw new Error("invalid investigation progress response");
  }
  const status = string(item.status);
  if (
    !toolProgressStatuses.includes(
      status as InvestigationStepProgress["status"],
    )
  ) {
    throw new Error("invalid investigation progress response");
  }
  return {
    position: integer(item.position),
    stepId: string(item.step_id),
    objective: string(item.objective),
    expectedSource: string(item.expected_source),
    dependsOn: item.depends_on.map(string),
    parallelGroup: integer(item.parallel_group),
    toolCallId: string(item.tool_call_id),
    toolName: string(item.tool_name),
    toolVersion: string(item.tool_version),
    status: status as InvestigationStepProgress["status"],
    failureCode: nullableString(item.failure_code),
    startedAt: nullableString(item.started_at),
    completedAt: nullableString(item.completed_at),
  };
}

function parsePlan(value: unknown): InvestigationPlanProgress {
  const item = record(value);
  if (!Array.isArray(item.steps) || item.steps.length === 0) {
    throw new Error("invalid investigation progress response");
  }
  return {
    attempt: integer(item.attempt),
    planId: string(item.plan_id),
    summary: string(item.summary),
    modelCallId: string(item.model_call_id),
    createdAt: string(item.created_at),
    steps: item.steps.map(parseStep),
  };
}

function parseReplan(value: unknown): ReplanProgress {
  const item = record(value);
  return {
    completedAttempt: integer(item.completed_attempt),
    nextAttempt: integer(item.next_attempt),
    decisionFingerprint: string(item.decision_fingerprint),
    reasonCode: string(item.reason_code),
    occurredAt: string(item.occurred_at),
  };
}

function parseRun(value: unknown): InvestigationProgress {
  const item = record(value);
  const budgets = record(item.budgets);
  if (
    !Array.isArray(item.plans) ||
    item.plans.length === 0 ||
    !Array.isArray(item.replans)
  ) {
    throw new Error("invalid investigation progress response");
  }
  const phase = string(item.phase);
  const status = string(item.status);
  if (
    !investigationPhases.includes(phase as InvestigationProgress["phase"]) ||
    !investigationStatuses.includes(status as InvestigationProgress["status"])
  ) {
    throw new Error("invalid investigation progress response");
  }
  return {
    schemaVersion: string(item.schema_version),
    workflowRunId: string(item.workflow_run_id),
    graphVersion: string(item.graph_version),
    phase: phase as InvestigationProgress["phase"],
    status: status as InvestigationProgress["status"],
    budgets: {
      steps: parseBudget(budgets.steps),
      replans: parseBudget(budgets.replans),
      toolCalls: parseBudget(budgets.tool_calls),
      modelCalls: parseBudget(budgets.model_calls),
      tokens: parseBudget(budgets.tokens),
      costNanounits: parseBudget(budgets.cost_nanounits),
    },
    plans: item.plans.map(parsePlan),
    replans: item.replans.map(parseReplan),
    checkpointSequence: integer(item.checkpoint_sequence),
    errorCode: nullableString(item.error_code),
    updatedAt: string(item.updated_at),
  };
}

export async function loadInvestigation(
  incidentId: string,
  signal?: AbortSignal,
): Promise<InvestigationProgress | null> {
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents/${encodeURIComponent(incidentId)}/investigation`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  if (!response.ok) {
    throw new Error(`Investigation request failed (${response.status})`);
  }
  const envelope = record(await response.json());
  return envelope.run === null ? null : parseRun(envelope.run);
}
