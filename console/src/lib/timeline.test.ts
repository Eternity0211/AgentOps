import { afterEach, describe, expect, it, vi } from "vitest";

import { loadTimeline } from "./timeline";

const common = {
  prior_version: 1,
  new_version: 2,
  actor_id: "operator-1",
  reason: "begin investigation",
  correlation_id: "correlation-1",
  causation_id: "command-1",
  occurred_at: "2026-10-11T10:05:00Z",
};

const transition = {
  ...common,
  kind: "transition",
  prior_state: "TRIAGED",
  new_state: "INVESTIGATING",
  state_when_requested: null,
  disposition: null,
};

const cancellation = {
  ...common,
  kind: "cancellation_request",
  state_when_requested: "EXECUTING",
  disposition: "DEFERRED",
  prior_state: null,
  new_state: null,
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

describe("loadTimeline", () => {
  it("maps both event kinds and preserves an opaque cursor", async () => {
    response({ items: [transition, cancellation], next_cursor: "opaque-next" });
    await expect(
      loadTimeline("incident / one", "opaque+current"),
    ).resolves.toEqual({
      items: [
        {
          kind: "transition",
          priorVersion: 1,
          newVersion: 2,
          actorId: "operator-1",
          reason: "begin investigation",
          correlationId: "correlation-1",
          causationId: "command-1",
          occurredAt: "2026-10-11T10:05:00Z",
          priorState: "TRIAGED",
          newState: "INVESTIGATING",
        },
        {
          kind: "cancellation_request",
          priorVersion: 1,
          newVersion: 2,
          actorId: "operator-1",
          reason: "begin investigation",
          correlationId: "correlation-1",
          causationId: "command-1",
          occurredAt: "2026-10-11T10:05:00Z",
          stateWhenRequested: "EXECUTING",
          disposition: "DEFERRED",
        },
      ],
      nextCursor: "opaque-next",
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/incidents/incident%20%2F%20one/timeline?limit=20&cursor=opaque%2Bcurrent",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("omits an absent cursor and rejects HTTP failure", async () => {
    response({}, 503);
    await expect(loadTimeline("incident-1")).rejects.toThrow("(503)");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/incidents/incident-1/timeline?limit=20",
      expect.any(Object),
    );
  });

  it.each([
    null,
    [],
    {},
    { items: "bad", next_cursor: null },
    { items: [], next_cursor: 1 },
    { items: [null], next_cursor: null },
    { items: [{ ...transition, prior_version: 0 }], next_cursor: null },
    { items: [{ ...transition, new_version: 3 }], next_cursor: null },
    { items: [{ ...transition, actor_id: "" }], next_cursor: null },
    { items: [{ ...transition, reason: null }], next_cursor: null },
    { items: [{ ...transition, correlation_id: "" }], next_cursor: null },
    { items: [{ ...transition, causation_id: 1 }], next_cursor: null },
    { items: [{ ...transition, occurred_at: "" }], next_cursor: null },
    { items: [{ ...transition, prior_state: null }], next_cursor: null },
    { items: [{ ...transition, new_state: "" }], next_cursor: null },
    {
      items: [{ ...cancellation, state_when_requested: null }],
      next_cursor: null,
    },
    { items: [{ ...cancellation, disposition: "" }], next_cursor: null },
    { items: [{ ...transition, kind: "unknown" }], next_cursor: null },
  ])("rejects invalid timeline payload %#", async (body) => {
    response(body);
    await expect(loadTimeline("incident-1")).rejects.toThrow(
      /invalid timeline/,
    );
  });
});
