import { afterEach, describe, expect, it, vi } from "vitest";

import { loadIncident, loadIncidents } from "./incidents";

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
        cursor: "opaque+cursor",
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
      "/api/v1/incidents?limit=20&severity=SEV2&state=INVESTIGATING&service=orders&cursor=opaque%2Bcursor",
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

describe("loadIncident", () => {
  const detail = {
    ...incident,
    closed_at: null,
    cancelled_at: "2026-10-11T10:10:00Z",
    cancellation_requested_at: "2026-10-11T10:09:00Z",
  };

  it("encodes the route identity and maps lifecycle timestamps", async () => {
    response(detail);
    await expect(loadIncident("incident / one")).resolves.toEqual({
      id: incident.id,
      service: incident.service,
      severity: incident.severity,
      state: incident.state,
      version: incident.version,
      openedAt: incident.opened_at,
      updatedAt: incident.updated_at,
      closedAt: null,
      cancelledAt: "2026-10-11T10:10:00Z",
      cancellationRequestedAt: "2026-10-11T10:09:00Z",
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/incidents/incident%20%2F%20one",
      expect.objectContaining({ cache: "no-store", credentials: "include" }),
    );
  });

  it("rejects an HTTP failure", async () => {
    response({}, 404);
    await expect(loadIncident("missing")).rejects.toThrow(
      "Incident detail request failed (404)",
    );
  });

  it.each([
    { ...detail, closed_at: 1 },
    { ...detail, cancelled_at: false },
    { ...detail, cancellation_requested_at: [] },
  ])("rejects invalid detail payload %#", async (body) => {
    response(body);
    await expect(loadIncident("incident-1")).rejects.toThrow(
      "invalid Incident detail response",
    );
  });
});
