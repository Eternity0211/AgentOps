import { afterEach, describe, expect, it, vi } from "vitest";

import { loadSession, SessionLoadError } from "./session";

const valid = {
  actor_id: "operator-1",
  tenant_id: "tenant-1",
  roles: ["OPERATOR"],
  permissions: ["incident:read", "approved_action:execute"],
};

function respond(body: unknown, init?: ResponseInit) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(typeof body === "string" ? body : JSON.stringify(body), {
        headers: { "Content-Type": "application/json", ...init?.headers },
        ...init,
      }),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("loadSession", () => {
  it("loads a validated same-origin session with credentials", async () => {
    respond(valid);

    await expect(loadSession()).resolves.toEqual({
      actorId: "operator-1",
      tenantId: "tenant-1",
      roles: ["OPERATOR"],
      permissions: ["incident:read", "approved_action:execute"],
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/session",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );
  });

  it.each([
    [401, "unauthenticated"],
    [403, "forbidden"],
    [503, "unavailable"],
  ] as const)("maps HTTP %s to %s", async (status, kind) => {
    respond({}, { status, headers: { "X-Request-ID": "request-1" } });
    await expect(loadSession()).rejects.toEqual(
      expect.objectContaining({ kind, requestId: "request-1" }),
    );
  });

  it.each([
    null,
    [],
    { ...valid, actor_id: "" },
    { ...valid, actor_id: "x".repeat(129) },
    { ...valid, tenant_id: null },
    { ...valid, roles: "OPERATOR" },
    { ...valid, roles: [] },
    { ...valid, roles: ["ROOT"] },
    { ...valid, roles: ["VIEWER", "VIEWER"] },
    { ...valid, permissions: "incident:read" },
    { ...valid, permissions: [""] },
    { ...valid, permissions: ["audit:read", "audit:read"] },
  ])("rejects an invalid principal payload %#", async (body) => {
    respond(body);
    await expect(loadSession()).rejects.toEqual(
      expect.objectContaining({ kind: "invalid" }),
    );
  });

  it("rejects malformed JSON with the response request ID", async () => {
    respond("not-json", { headers: { "X-Request-ID": "request-json" } });
    await expect(loadSession()).rejects.toEqual(
      expect.objectContaining({ kind: "invalid", requestId: "request-json" }),
    );
  });

  it("classifies network failure while preserving cancellation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(loadSession()).rejects.toEqual(
      expect.objectContaining({ kind: "unavailable", requestId: null }),
    );

    const aborted = new DOMException("cancelled", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(aborted));
    await expect(loadSession()).rejects.toBe(aborted);
  });

  it("uses a stable typed error identity", () => {
    const error = new SessionLoadError("forbidden", null);
    expect(error.name).toBe("SessionLoadError");
    expect(error.message).toBe("forbidden");
  });
});
