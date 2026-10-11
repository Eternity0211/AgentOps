import { consoleConfig } from "./config";

export const roles = ["VIEWER", "OPERATOR", "APPROVER", "ADMIN"] as const;
export type Role = (typeof roles)[number];

export interface SessionPrincipal {
  actorId: string;
  tenantId: string;
  roles: Role[];
  permissions: string[];
}

export type SessionErrorKind =
  "unauthenticated" | "forbidden" | "unavailable" | "invalid";

export class SessionLoadError extends Error {
  constructor(
    public readonly kind: SessionErrorKind,
    public readonly requestId: string | null,
  ) {
    super(kind);
    this.name = "SessionLoadError";
  }
}

function isBoundedIdentifier(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 128;
}

function parseSession(value: unknown): SessionPrincipal {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new SessionLoadError("invalid", null);
  }
  const record = value as Record<string, unknown>;
  if (
    !isBoundedIdentifier(record.actor_id) ||
    !isBoundedIdentifier(record.tenant_id) ||
    !Array.isArray(record.roles) ||
    record.roles.length === 0 ||
    !record.roles.every((role) => roles.includes(role as Role)) ||
    new Set(record.roles).size !== record.roles.length ||
    !Array.isArray(record.permissions) ||
    !record.permissions.every(isBoundedIdentifier) ||
    new Set(record.permissions).size !== record.permissions.length
  ) {
    throw new SessionLoadError("invalid", null);
  }
  return {
    actorId: record.actor_id,
    tenantId: record.tenant_id,
    roles: record.roles as Role[],
    permissions: record.permissions,
  };
}

export async function loadSession(
  signal?: AbortSignal,
): Promise<SessionPrincipal> {
  let response: Response;
  try {
    response = await fetch(`${consoleConfig.apiBaseUrl}/session`, {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new SessionLoadError("unavailable", null);
  }
  const requestId = response.headers.get("X-Request-ID");
  if (response.status === 401) {
    throw new SessionLoadError("unauthenticated", requestId);
  }
  if (response.status === 403) {
    throw new SessionLoadError("forbidden", requestId);
  }
  if (!response.ok) {
    throw new SessionLoadError("unavailable", requestId);
  }
  try {
    return parseSession(await response.json());
  } catch (error) {
    if (error instanceof SessionLoadError) {
      throw error;
    }
    throw new SessionLoadError("invalid", requestId);
  }
}
