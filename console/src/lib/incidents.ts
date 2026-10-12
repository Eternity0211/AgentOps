import { consoleConfig } from "./config";

export const severities = ["SEV1", "SEV2", "SEV3", "SEV4"] as const;
export const incidentStates = [
  "DETECTED",
  "TRIAGED",
  "INVESTIGATING",
  "EVIDENCE_REVIEW",
  "NEEDS_HUMAN",
  "PLANNING_REMEDIATION",
  "POLICY_REVIEW",
  "AWAITING_APPROVAL",
  "READY_TO_EXECUTE",
  "EXECUTING",
  "VERIFYING",
  "CLOSED",
  "CANCELLED",
] as const;

export interface IncidentSummary {
  id: string;
  service: string;
  severity: (typeof severities)[number];
  state: (typeof incidentStates)[number];
  version: number;
  openedAt: string;
  updatedAt: string;
}

export interface IncidentDetail extends IncidentSummary {
  closedAt: string | null;
  cancelledAt: string | null;
  cancellationRequestedAt: string | null;
}

export interface IncidentFilters {
  severity?: string;
  state?: string;
  service?: string;
  cursor?: string;
}

export interface IncidentPage {
  items: IncidentSummary[];
  nextCursor: string | null;
}

function parseIncident(value: unknown): IncidentSummary {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid Incident response");
  }
  const row = value as Record<string, unknown>;
  if (
    typeof row.id !== "string" ||
    typeof row.service !== "string" ||
    !severities.includes(row.severity as IncidentSummary["severity"]) ||
    !incidentStates.includes(row.state as IncidentSummary["state"]) ||
    !Number.isInteger(row.version) ||
    (row.version as number) < 1 ||
    typeof row.opened_at !== "string" ||
    typeof row.updated_at !== "string"
  ) {
    throw new Error("invalid Incident response");
  }
  return {
    id: row.id,
    service: row.service,
    severity: row.severity as IncidentSummary["severity"],
    state: row.state as IncidentSummary["state"],
    version: row.version as number,
    openedAt: row.opened_at,
    updatedAt: row.updated_at,
  };
}

function nullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function parseIncidentDetail(value: unknown): IncidentDetail {
  const summary = parseIncident(value);
  const row = value as Record<string, unknown>;
  if (
    !nullableString(row.closed_at) ||
    !nullableString(row.cancelled_at) ||
    !nullableString(row.cancellation_requested_at)
  ) {
    throw new Error("invalid Incident detail response");
  }
  return {
    ...summary,
    closedAt: row.closed_at,
    cancelledAt: row.cancelled_at,
    cancellationRequestedAt: row.cancellation_requested_at,
  };
}

async function responseBody(
  response: Response,
  label: string,
): Promise<unknown> {
  if (!response.ok)
    throw new Error(`${label} request failed (${response.status})`);
  return response.json() as Promise<unknown>;
}

export async function loadIncidents(
  filters: IncidentFilters,
  signal?: AbortSignal,
): Promise<IncidentPage> {
  const query = new URLSearchParams({ limit: "20" });
  for (const key of ["severity", "state", "service"] as const) {
    const value = filters[key]?.trim();
    if (value) query.set(key, value);
  }
  if (filters.cursor) query.set("cursor", filters.cursor);
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents?${query}`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  const body = await responseBody(response, "Incident");
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new Error("invalid Incident page response");
  }
  const page = body as Record<string, unknown>;
  if (
    !Array.isArray(page.items) ||
    !(typeof page.next_cursor === "string" || page.next_cursor === null)
  ) {
    throw new Error("invalid Incident page response");
  }
  return {
    items: page.items.map(parseIncident),
    nextCursor: page.next_cursor,
  };
}

export async function loadIncident(
  incidentId: string,
  signal?: AbortSignal,
): Promise<IncidentDetail> {
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents/${encodeURIComponent(incidentId)}`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  return parseIncidentDetail(await responseBody(response, "Incident detail"));
}
