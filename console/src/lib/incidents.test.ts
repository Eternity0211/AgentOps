import { afterEach, describe, expect, it, vi } from "vitest";

import { loadIncidents } from "./incidents";

const incident = {
  id: "incident-1",
  service: "orders",
  severity: "SEV2",
  state: "INVESTIGATING",
  version: 3,
  opened_at: "2026-10-11T10:00:00Z",
  updated_at: "2026-10-11T10:05:00Z",
};

function response(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("loadIncidents", () => {
  it("requests bounded filters and maps the versioned page", async () => {
    response({ items: [incident], next_cursor: "opaque-next" });
    await expect(
      loadIncidents({
        severity: " SEV2 ",
        state: "INVESTIGATING",
        service: " orders ",
        cursor: " opaque ",
      }),
    ).resolves.toEqual({
      items: [
        {
          id: "incident-1",
          service: "orders",
          severity: "SEV2",
          state: "INVESTIGATING",
          version: 3,
          openedAt: "2026-10-11T10:00:00Z",
          updatedAt: "2026-10-11T10:05:00Z",
        },
      ],
      nextCursor: "opaque-next",
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/incidents?limit=20&severity=SEV2&state=INVESTIGATING&service=orders&cursor=opaque",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("omits empty filters and rejects HTTP failure", async () => {
    response({}, 503);
    await expect(loadIncidents({ service: " " })).rejects.toThrow("(503)");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/incidents?limit=20",
      expect.any(Object),
    );
  });

  it.each([
    null,
    [],
    {},
    { items: "bad", next_cursor: null },
    { items: [], next_cursor: 3 },
    { items: [null], next_cursor: null },
    { items: [{ ...incident, id: 1 }], next_cursor: null },
    { items: [{ ...incident, service: null }], next_cursor: null },
    { items: [{ ...incident, severity: "SEV9" }], next_cursor: null },
    { items: [{ ...incident, state: "UNKNOWN" }], next_cursor: null },
    { items: [{ ...incident, version: 0 }], next_cursor: null },
    { items: [{ ...incident, version: 1.5 }], next_cursor: null },
    { items: [{ ...incident, opened_at: null }], next_cursor: null },
    { items: [{ ...incident, updated_at: null }], next_cursor: null },
  ])("rejects invalid page payload %#", async (body) => {
    response(body);
    await expect(loadIncidents({})).rejects.toThrow(/invalid Incident/);
  });
});
