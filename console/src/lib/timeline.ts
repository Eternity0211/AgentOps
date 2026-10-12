import { consoleConfig } from "./config";

interface TimelineEventBase {
  priorVersion: number;
  newVersion: number;
  actorId: string;
  reason: string;
  correlationId: string;
  causationId: string;
  occurredAt: string;
}

export interface TransitionTimelineEvent extends TimelineEventBase {
  kind: "transition";
  priorState: string;
  newState: string;
}

export interface CancellationTimelineEvent extends TimelineEventBase {
  kind: "cancellation_request";
  stateWhenRequested: string;
  disposition: string;
}

export type TimelineEvent = TransitionTimelineEvent | CancellationTimelineEvent;

export interface TimelinePage {
  items: TimelineEvent[];
  nextCursor: string | null;
}

function nonemptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function parseEvent(value: unknown): TimelineEvent {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid timeline event response");
  }
  const row = value as Record<string, unknown>;
  if (
    !Number.isInteger(row.prior_version) ||
    (row.prior_version as number) < 1 ||
    !Number.isInteger(row.new_version) ||
    row.new_version !== (row.prior_version as number) + 1 ||
    !nonemptyString(row.actor_id) ||
    !nonemptyString(row.reason) ||
    !nonemptyString(row.correlation_id) ||
    !nonemptyString(row.causation_id) ||
    !nonemptyString(row.occurred_at)
  ) {
    throw new Error("invalid timeline event response");
  }
  const common = {
    priorVersion: row.prior_version as number,
    newVersion: row.new_version as number,
    actorId: row.actor_id,
    reason: row.reason,
    correlationId: row.correlation_id,
    causationId: row.causation_id,
    occurredAt: row.occurred_at,
  };
  if (
    row.kind === "transition" &&
    nonemptyString(row.prior_state) &&
    nonemptyString(row.new_state)
  ) {
    return {
      kind: "transition",
      ...common,
      priorState: row.prior_state,
      newState: row.new_state,
    };
  }
  if (
    row.kind === "cancellation_request" &&
    nonemptyString(row.state_when_requested) &&
    nonemptyString(row.disposition)
  ) {
    return {
      kind: "cancellation_request",
      ...common,
      stateWhenRequested: row.state_when_requested,
      disposition: row.disposition,
    };
  }
  throw new Error("invalid timeline event response");
}

export async function loadTimeline(
  incidentId: string,
  cursor?: string,
  signal?: AbortSignal,
): Promise<TimelinePage> {
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) query.set("cursor", cursor);
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents/${encodeURIComponent(incidentId)}/timeline?${query}`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  if (!response.ok) {
    throw new Error(`Timeline request failed (${response.status})`);
  }
  const body: unknown = await response.json();
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new Error("invalid timeline page response");
  }
  const page = body as Record<string, unknown>;
  if (
    !Array.isArray(page.items) ||
    !(typeof page.next_cursor === "string" || page.next_cursor === null)
  ) {
    throw new Error("invalid timeline page response");
  }
  return {
    items: page.items.map(parseEvent),
    nextCursor: page.next_cursor,
  };
}
