import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadInvestigation } from "./investigation";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

function response(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function validEnvelope() {
  return {
    run: {
      schema_version: "1.0.0",
      workflow_run_id: "run-1",
      graph_version: "1.0.0",
      phase: "INVESTIGATING",
      status: "ACTIVE",
      budgets: {
        steps: { used: 1, maximum: 4, remaining: 3 },
        replans: { used: 1, maximum: 2, remaining: 1 },
        tool_calls: { used: 1, maximum: 4, remaining: 3 },
        model_calls: { used: 2, maximum: 6, remaining: 4 },
        tokens: { used: 100, maximum: 1000, remaining: 900 },
        cost_nanounits: { used: 10, maximum: 100, remaining: 90 },
      },
      plans: [
        {
          attempt: 1,
          plan_id: "plan-1",
          summary: "Collect independent evidence",
          model_call_id: "model-1",
          created_at: "2026-10-12T08:01:00Z",
          steps: [
            {
              position: 1,
              step_id: "metrics",
              objective: "Inspect error rate",
              expected_source: "METRIC",
              depends_on: [],
              parallel_group: 0,
              tool_call_id: "call-1",
              tool_name: "query_metrics",
              tool_version: "1.0.0",
              status: "SUCCEEDED",
              failure_code: null,
              started_at: "2026-10-12T08:02:00Z",
              completed_at: "2026-10-12T08:03:00Z",
            },
          ],
        },
      ],
      replans: [
        {
          completed_attempt: 1,
          next_attempt: 2,
          decision_fingerprint: "a".repeat(64),
          reason_code: "MORE_EVIDENCE_REQUIRED",
          occurred_at: "2026-10-12T08:04:00Z",
        },
      ],
      checkpoint_sequence: 4,
      error_code: null,
      updated_at: "2026-10-12T08:04:00Z",
    },
  };
}

beforeEach(() => fetchMock.mockReset());

describe("loadInvestigation", () => {
  it("loads and maps the bounded server projection", async () => {
    fetchMock.mockResolvedValue(response(validEnvelope()));
    const controller = new AbortController();

    await expect(
      loadInvestigation("incident / one", controller.signal),
    ).resolves.toMatchObject({
      workflowRunId: "run-1",
      phase: "INVESTIGATING",
      status: "ACTIVE",
      budgets: {
        replans: { used: 1, maximum: 2, remaining: 1 },
        toolCalls: { used: 1, maximum: 4, remaining: 3 },
        modelCalls: { used: 2, maximum: 6, remaining: 4 },
        costNanounits: { used: 10, maximum: 100, remaining: 90 },
      },
      plans: [
        {
          attempt: 1,
          modelCallId: "model-1",
          steps: [
            {
              stepId: "metrics",
              dependsOn: [],
              toolCallId: "call-1",
              status: "SUCCEEDED",
              failureCode: null,
            },
          ],
        },
      ],
      replans: [{ completedAttempt: 1, nextAttempt: 2 }],
      errorCode: null,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/incidents/incident%20%2F%20one/investigation",
      expect.objectContaining({
        cache: "no-store",
        credentials: "include",
        signal: controller.signal,
      }),
    );
  });

  it("returns the authoritative no-run state", async () => {
    fetchMock.mockResolvedValue(response({ run: null }));
    await expect(loadInvestigation("incident-1")).resolves.toBeNull();
  });

  it("reports HTTP failures", async () => {
    fetchMock.mockResolvedValue(response({}, false, 409));
    await expect(loadInvestigation("incident-1")).rejects.toThrow(
      "Investigation request failed (409)",
    );
  });

  it.each([
    1,
    null,
    [],
    { run: 1 },
    { run: { ...validEnvelope().run, schema_version: "" } },
    { run: { ...validEnvelope().run, error_code: 2 } },
    { run: { ...validEnvelope().run, checkpoint_sequence: -1 } },
    { run: { ...validEnvelope().run, checkpoint_sequence: 1.5 } },
    { run: { ...validEnvelope().run, phase: "UNKNOWN" } },
    { run: { ...validEnvelope().run, status: "UNKNOWN" } },
    { run: { ...validEnvelope().run, plans: "bad" } },
    { run: { ...validEnvelope().run, plans: [] } },
    { run: { ...validEnvelope().run, replans: "bad" } },
  ])("rejects an invalid envelope or run %#", async (body) => {
    fetchMock.mockResolvedValue(response(body));
    await expect(loadInvestigation("incident-1")).rejects.toThrow(
      "invalid investigation progress response",
    );
  });

  it.each([
    { used: 5, maximum: 4, remaining: 0 },
    { used: 1, maximum: 4, remaining: 2 },
    { used: "1", maximum: 4, remaining: 3 },
  ])("rejects an inconsistent budget %#", async (budget) => {
    const body = validEnvelope();
    body.run.budgets.steps = budget as never;
    fetchMock.mockResolvedValue(response(body));
    await expect(loadInvestigation("incident-1")).rejects.toThrow(
      "invalid investigation progress response",
    );
  });

  it.each([
    { key: "depends_on", value: "bad" },
    { key: "status", value: "UNKNOWN" },
    { key: "objective", value: 1 },
  ])("rejects an invalid step field %#", async ({ key, value }) => {
    const body = validEnvelope();
    Object.assign(body.run.plans[0]!.steps[0]!, { [key]: value });
    fetchMock.mockResolvedValue(response(body));
    await expect(loadInvestigation("incident-1")).rejects.toThrow(
      "invalid investigation progress response",
    );
  });

  it.each(["bad", []])("rejects invalid plan steps %#", async (steps) => {
    const body = validEnvelope();
    body.run.plans[0]!.steps = steps as never;
    fetchMock.mockResolvedValue(response(body));
    await expect(loadInvestigation("incident-1")).rejects.toThrow(
      "invalid investigation progress response",
    );
  });

  it("rejects invalid replan fields", async () => {
    const body = validEnvelope();
    body.run.replans[0]!.next_attempt = -1;
    fetchMock.mockResolvedValue(response(body));
    await expect(loadInvestigation("incident-1")).rejects.toThrow(
      "invalid investigation progress response",
    );
  });
});
