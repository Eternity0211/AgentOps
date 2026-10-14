import { consoleConfig } from "./config";

export type ModelCallStatus =
  "STARTED" | "SUCCEEDED" | "FAILED" | "TIMED_OUT" | "REFUSED";

export interface PlatformModelCall {
  id: string;
  workflowRunId: string;
  node: string;
  attempt: number;
  promptId: string;
  promptVersion: string;
  promptFingerprint: string;
  provider: string;
  model: string;
  status: ModelCallStatus;
  startedAt: string;
  completedAt: string | null;
  durationMs: number | null;
  tokenUsage: TokenUsage | null;
  cost: ModelCost | null;
  meteringUnavailableReason: string | null;
  failureCode: string | null;
  correlationId: string;
  causationId: string;
  requestHash: string;
  responseHash: string | null;
  inputSchemaVersion: string;
  outputSchemaVersion: string;
  schemaVersion: string;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  cachedInputTokens: number;
  reasoningTokens: number;
  totalTokens: number;
}

export interface ModelCost {
  amountNanounits: number;
  currency: string;
  source: string;
  rateCardVersion: string;
}

export interface CheckpointProjection {
  workflowRunId: string;
  graphVersion: string;
  phase: string;
  status: string;
  checkpointSequence: number;
  projectionFingerprint: string;
  observedAt: string;
  scope: "LATEST_DURABLE_PROJECTION";
}

export interface AuditRequirement {
  modelCallId: string;
  eventType: "model.call_started" | "model.call_finished";
  status: "PRESENT" | "MISSING" | "DUPLICATE";
  observedSequences: number[];
}

export interface PlatformObservability {
  modelCalls: PlatformModelCall[];
  modelCallsTruncated: boolean;
  usage: {
    callCount: number;
    meteredCallCount: number;
    unavailableCallCount: number;
    pendingCallCount: number;
    statuses: Record<
      "started" | "succeeded" | "failed" | "timedOut" | "refused",
      number
    >;
    tokens: TokenUsage;
    costs: Array<{ currency: string; amountNanounits: number }>;
  };
  checkpoints: CheckpointProjection[];
  checkpointsTruncated: boolean;
  audit: {
    status: "COMPLETE" | "INCOMPLETE" | "PARTIAL";
    complete: boolean;
    scope: "DISPLAYED_MODEL_CALLS";
    expectedEventCount: number;
    observedEventCount: number;
    missingEventCount: number;
    duplicateEventCount: number;
    requirements: AuditRequirement[];
    rulesVersion: "1.0.0";
  };
}

const SHA256 = /^[a-f0-9]{64}$/;
const CURRENCY = /^[A-Z]{3}$/;
const STATUSES: ModelCallStatus[] = [
  "STARTED",
  "SUCCEEDED",
  "FAILED",
  "TIMED_OUT",
  "REFUSED",
];

function invalid(): never {
  throw new Error("invalid platform observability response");
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return invalid();
  return value as Record<string, unknown>;
}

function string(value: unknown): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 512)
    return invalid();
  return value;
}

function nullableString(value: unknown): string | null {
  return value === null ? null : string(value);
}

function integer(value: unknown, maximum = Number.MAX_SAFE_INTEGER): number {
  if (
    !Number.isSafeInteger(value) ||
    (value as number) < 0 ||
    (value as number) > maximum
  )
    return invalid();
  return value as number;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") return invalid();
  return value;
}

function instant(value: unknown): string {
  const result = string(value);
  if (!Number.isFinite(Date.parse(result))) return invalid();
  return result;
}

function hash(value: unknown): string {
  const result = string(value);
  if (!SHA256.test(result)) return invalid();
  return result;
}

function tokens(value: unknown): TokenUsage {
  const item = record(value);
  const result = {
    inputTokens: integer(item.input_tokens),
    outputTokens: integer(item.output_tokens),
    cachedInputTokens: integer(item.cached_input_tokens),
    reasoningTokens: integer(item.reasoning_tokens),
    totalTokens: integer(item.total_tokens),
  };
  if (
    result.totalTokens !== result.inputTokens + result.outputTokens ||
    result.cachedInputTokens > result.inputTokens ||
    result.reasoningTokens > result.outputTokens
  )
    return invalid();
  return result;
}

function cost(value: unknown): ModelCost {
  const item = record(value);
  const currency = string(item.currency);
  if (!CURRENCY.test(currency)) return invalid();
  return {
    amountNanounits: integer(item.amount_nanounits),
    currency,
    source: string(item.source),
    rateCardVersion: string(item.rate_card_version),
  };
}

function modelCall(value: unknown): PlatformModelCall {
  const item = record(value);
  const status = string(item.status) as ModelCallStatus;
  if (!STATUSES.includes(status)) return invalid();
  const startedAt = instant(item.started_at);
  const completedAt =
    item.completed_at === null ? null : instant(item.completed_at);
  const durationMs =
    item.duration_ms === null ? null : integer(item.duration_ms);
  const tokenUsage =
    item.token_usage === null ? null : tokens(item.token_usage);
  const modelCost = item.cost === null ? null : cost(item.cost);
  const unavailable = nullableString(item.metering_unavailable_reason);
  const failureCode = nullableString(item.failure_code);
  const responseHash =
    item.response_hash === null ? null : hash(item.response_hash);
  if (status === "STARTED") {
    if (
      completedAt !== null ||
      durationMs !== null ||
      tokenUsage !== null ||
      modelCost !== null ||
      unavailable !== null ||
      failureCode !== null ||
      responseHash !== null
    )
      return invalid();
  } else {
    if (completedAt === null || durationMs === null) return invalid();
    if (Date.parse(completedAt) < Date.parse(startedAt)) return invalid();
    if (durationMs !== Date.parse(completedAt) - Date.parse(startedAt))
      return invalid();
    if ((tokenUsage === null) !== (modelCost === null)) return invalid();
    if ((tokenUsage === null) === (unavailable === null)) return invalid();
    if (status === "SUCCEEDED") {
      if (failureCode !== null || responseHash === null) return invalid();
    } else if (failureCode === null) return invalid();
  }
  return {
    id: string(item.id),
    workflowRunId: string(item.workflow_run_id),
    node: string(item.node),
    attempt: integer(item.attempt),
    promptId: string(item.prompt_id),
    promptVersion: string(item.prompt_version),
    promptFingerprint: hash(item.prompt_fingerprint),
    provider: string(item.provider),
    model: string(item.model),
    status,
    startedAt,
    completedAt,
    durationMs,
    tokenUsage,
    cost: modelCost,
    meteringUnavailableReason: unavailable,
    failureCode,
    correlationId: string(item.correlation_id),
    causationId: string(item.causation_id),
    requestHash: hash(item.request_hash),
    responseHash,
    inputSchemaVersion: string(item.input_schema_version),
    outputSchemaVersion: string(item.output_schema_version),
    schemaVersion: string(item.schema_version),
  };
}

function checkpoint(value: unknown): CheckpointProjection {
  const item = record(value);
  if (item.scope !== "LATEST_DURABLE_PROJECTION") return invalid();
  return {
    workflowRunId: string(item.workflow_run_id),
    graphVersion: string(item.graph_version),
    phase: string(item.phase),
    status: string(item.status),
    checkpointSequence: integer(item.checkpoint_sequence),
    projectionFingerprint: hash(item.projection_fingerprint),
    observedAt: instant(item.observed_at),
    scope: "LATEST_DURABLE_PROJECTION",
  };
}

function requirement(value: unknown): AuditRequirement {
  const item = record(value);
  const eventType = item.event_type;
  const status = item.status;
  if (
    (eventType !== "model.call_started" &&
      eventType !== "model.call_finished") ||
    (status !== "PRESENT" && status !== "MISSING" && status !== "DUPLICATE") ||
    !Array.isArray(item.observed_sequences)
  )
    return invalid();
  const sequences = item.observed_sequences.map((value) => integer(value));
  if (
    new Set(sequences).size !== sequences.length ||
    (status === "MISSING" && sequences.length !== 0) ||
    (status === "PRESENT" && sequences.length !== 1) ||
    (status === "DUPLICATE" && sequences.length < 2)
  )
    return invalid();
  return {
    modelCallId: string(item.model_call_id),
    eventType,
    status,
    observedSequences: sequences,
  };
}

export function parsePlatformObservability(
  value: unknown,
): PlatformObservability {
  const root = record(value);
  if (!Array.isArray(root.model_calls) || !Array.isArray(root.checkpoints))
    return invalid();
  const modelCalls = root.model_calls.map(modelCall);
  const modelCallsTruncated = boolean(root.model_calls_truncated);
  if (
    new Set(modelCalls.map((item) => item.id)).size !== modelCalls.length ||
    modelCalls.some(
      (item, index) =>
        index > 0 &&
        Date.parse(modelCalls[index - 1]!.startedAt) <
          Date.parse(item.startedAt),
    )
  )
    return invalid();

  const usageRow = record(root.usage);
  const statusesRow = record(usageRow.statuses);
  const usage = {
    callCount: integer(usageRow.call_count),
    meteredCallCount: integer(usageRow.metered_call_count),
    unavailableCallCount: integer(usageRow.unavailable_call_count),
    pendingCallCount: integer(usageRow.pending_call_count),
    statuses: {
      started: integer(statusesRow.started),
      succeeded: integer(statusesRow.succeeded),
      failed: integer(statusesRow.failed),
      timedOut: integer(statusesRow.timed_out),
      refused: integer(statusesRow.refused),
    },
    tokens: tokens(usageRow.tokens),
    costs: Array.isArray(usageRow.costs)
      ? usageRow.costs.map((value) => {
          const item = record(value);
          const currency = string(item.currency);
          if (!CURRENCY.test(currency)) return invalid();
          return { currency, amountNanounits: integer(item.amount_nanounits) };
        })
      : invalid(),
  };
  const statusCounts = {
    STARTED: usage.statuses.started,
    SUCCEEDED: usage.statuses.succeeded,
    FAILED: usage.statuses.failed,
    TIMED_OUT: usage.statuses.timedOut,
    REFUSED: usage.statuses.refused,
  };
  const measuredTokens = modelCalls.reduce(
    (sum, item) => ({
      inputTokens: sum.inputTokens + (item.tokenUsage?.inputTokens ?? 0),
      outputTokens: sum.outputTokens + (item.tokenUsage?.outputTokens ?? 0),
      cachedInputTokens:
        sum.cachedInputTokens + (item.tokenUsage?.cachedInputTokens ?? 0),
      reasoningTokens:
        sum.reasoningTokens + (item.tokenUsage?.reasoningTokens ?? 0),
      totalTokens: sum.totalTokens + (item.tokenUsage?.totalTokens ?? 0),
    }),
    {
      inputTokens: 0,
      outputTokens: 0,
      cachedInputTokens: 0,
      reasoningTokens: 0,
      totalTokens: 0,
    },
  );
  const measuredCosts = new Map<string, number>();
  for (const item of modelCalls) {
    if (item.cost)
      measuredCosts.set(
        item.cost.currency,
        (measuredCosts.get(item.cost.currency) ?? 0) +
          item.cost.amountNanounits,
      );
  }
  if (
    usage.callCount !== modelCalls.length ||
    usage.pendingCallCount !== statusCounts.STARTED ||
    usage.meteredCallCount !==
      modelCalls.filter((item) => item.tokenUsage !== null).length ||
    usage.unavailableCallCount !==
      modelCalls.filter((item) => item.meteringUnavailableReason !== null)
        .length ||
    STATUSES.some(
      (status) =>
        statusCounts[status] !==
        modelCalls.filter((item) => item.status === status).length,
    ) ||
    JSON.stringify(usage.tokens) !== JSON.stringify(measuredTokens) ||
    new Set(usage.costs.map((item) => item.currency)).size !==
      usage.costs.length ||
    usage.costs.some(
      (item) => measuredCosts.get(item.currency) !== item.amountNanounits,
    ) ||
    usage.costs.length !== measuredCosts.size
  )
    return invalid();

  const checkpoints = root.checkpoints.map(checkpoint);
  if (
    new Set(checkpoints.map((item) => item.workflowRunId)).size !==
      checkpoints.length ||
    checkpoints.some(
      (item, index) =>
        index > 0 &&
        Date.parse(checkpoints[index - 1]!.observedAt) <
          Date.parse(item.observedAt),
    )
  )
    return invalid();

  const auditRow = record(root.audit);
  if (!Array.isArray(auditRow.requirements)) return invalid();
  const requirements = auditRow.requirements.map(requirement);
  const expectedKeys = modelCalls.flatMap((item) => [
    `${item.id}:model.call_started`,
    ...(item.status === "STARTED" ? [] : [`${item.id}:model.call_finished`]),
  ]);
  const actualKeys = requirements.map(
    (item) => `${item.modelCallId}:${item.eventType}`,
  );
  const expectedEventCount = integer(auditRow.expected_event_count);
  const observedEventCount = integer(auditRow.observed_event_count);
  const missingEventCount = integer(auditRow.missing_event_count);
  const duplicateEventCount = integer(auditRow.duplicate_event_count);
  const auditStatus = string(auditRow.status);
  const complete = boolean(auditRow.complete);
  if (
    !["COMPLETE", "INCOMPLETE", "PARTIAL"].includes(auditStatus) ||
    auditRow.scope !== "DISPLAYED_MODEL_CALLS" ||
    auditRow.rules_version !== "1.0.0" ||
    expectedKeys.length !== actualKeys.length ||
    expectedKeys.some((key, index) => key !== actualKeys[index]) ||
    expectedEventCount !== requirements.length ||
    observedEventCount !==
      requirements.reduce(
        (sum, item) => sum + item.observedSequences.length,
        0,
      ) ||
    missingEventCount !==
      requirements.filter((item) => item.status === "MISSING").length ||
    duplicateEventCount !==
      requirements.filter((item) => item.status === "DUPLICATE").length ||
    complete !==
      (!modelCallsTruncated &&
        missingEventCount === 0 &&
        duplicateEventCount === 0) ||
    auditStatus !==
      (modelCallsTruncated ? "PARTIAL" : complete ? "COMPLETE" : "INCOMPLETE")
  )
    return invalid();

  return {
    modelCalls,
    modelCallsTruncated,
    usage,
    checkpoints,
    checkpointsTruncated: boolean(root.checkpoints_truncated),
    audit: {
      status: auditStatus as "COMPLETE" | "INCOMPLETE" | "PARTIAL",
      complete,
      scope: "DISPLAYED_MODEL_CALLS",
      expectedEventCount,
      observedEventCount,
      missingEventCount,
      duplicateEventCount,
      requirements,
      rulesVersion: "1.0.0",
    },
  };
}

export async function loadPlatformObservability(
  incidentId: string,
  signal?: AbortSignal,
): Promise<PlatformObservability> {
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents/${encodeURIComponent(incidentId)}/platform-observability`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  if (!response.ok)
    throw new Error(
      `Platform observability request failed (${response.status})`,
    );
  return parsePlatformObservability(await response.json());
}
