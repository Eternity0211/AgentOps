import { describe, expect, it } from "vitest";

import { isActivePath, navigationFor } from "./navigation";
import type { SessionPrincipal } from "./session";

function principal(permissions: string[]): SessionPrincipal {
  return {
    actorId: "actor-1",
    tenantId: "tenant-1",
    roles: ["VIEWER"],
    permissions,
  };
}

describe("navigationFor", () => {
  it("shows only destinations backed by server-derived permissions", () => {
    expect(navigationFor(principal([])).map((item) => item.label)).toEqual([
      "Overview",
    ]);
    expect(
      navigationFor(
        principal([
          "incident:read",
          "approved_action:execute",
          "approval:decide",
          "audit:read",
          "admin:manage",
        ]),
      ).map((item) => item.label),
    ).toEqual([
      "Overview",
      "Incidents",
      "Operations",
      "Approvals",
      "Audit",
      "Administration",
    ]);
  });

  it("matches root exactly and nested destinations by segment", () => {
    expect(isActivePath("/", "/")).toBe(true);
    expect(isActivePath("/incidents", "/")).toBe(false);
    expect(isActivePath("/incidents", "/incidents")).toBe(true);
    expect(isActivePath("/incidents/one", "/incidents")).toBe(true);
    expect(isActivePath("/incidentally", "/incidents")).toBe(false);
  });
});
