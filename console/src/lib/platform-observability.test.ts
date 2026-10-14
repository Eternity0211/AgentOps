import { afterEach, describe, expect, it, vi } from "vitest";

import {
  loadPlatformObservability,
  parsePlatformObservability,
} from "./platform-observability";

function response() {
  return {
    model_calls: [
      {
        id: "call-success",
        workflow_run_id: "run-1",
        node: "diagnosis.hypothesis",
        attempt: 1,
        prompt_id: "prompt-1",
        prompt_version: "1.0.0",
        prompt_fingerprint: "1".repeat(64),
        provider: "mock",
        model: "deterministic",
        status: "SUCCEEDED",
        started_at: "2026-10-14T10:00:00Z",
        completed_at: "2026-10-14T10:00:02Z",
        duration_ms: 2000,
        token_usage: {
          input_tokens: 100,
          output_tokens: 20,
          cached_input_tokens: 10,
          reasoning_tokens: 5,
          total_tokens: 120,
        },
        cost: {
          amount_nanounits: 12345,
          currency: "USD",
          source: "RATE_CARD_CALCULATED",
          rate_card_version: "1.0.0",
        },
        metering_unavailable_reason: null,
        failure_code: null,
        correlation_id: "correlation-1",
        causation_id: "node-1",
        request_hash: "2".repeat(64),
        response_hash: "3".repeat(64),
        input_schema_version: "1.0.0",
        output_schema_version: "1.0.0",
        schema_version: "1.0.0",
      },
      {
        id: "call-timeout",
        workflow_run_id: "run-1",
        node: "diagnosis.plan",
        attempt: 2,
        prompt_id: "prompt-1",
        prompt_version: "1.0.0",
        prompt_fingerprint: "4".repeat(64),
        provider: "mock",
        model: "deterministic",
        status: "TIMED_OUT",
        started_at: "2026-10-14T09:59:00Z",
        completed_at: "2026-10-14T09:59:01Z",
        duration_ms: 1000,
        token_usage: null,
        cost: null,
        metering_unavailable_reason: "CALL_FAILED_BEFORE_METERING",
        failure_code: "provider_timeout",
        correlation_id: "correlation-1",
        causation_id: "node-2",
        request_hash: "5".repeat(64),
        response_hash: null,
        input_schema_version: "1.0.0",
        output_schema_version: "1.0.0",
        schema_version: "1.0.0",
      },
    ],
    model_calls_truncated: false,
    usage: {
      call_count: 2,
      metered_call_count: 1,
      unavailable_call_count: 1,
      pending_call_count: 0,
      statuses: {
        started: 0,
        succeeded: 1,
        failed: 0,
        timed_out: 1,
        refused: 0,
      },
      tokens: {
        input_tokens: 100,
        output_tokens: 20,
        cached_input_tokens: 10,
        reasoning_tokens: 5,
        total_tokens: 120,
      },
      costs: [{ currency: "USD", amount_nanounits: 12345 }],
    },
    checkpoints: [
      {
        workflow_run_id: "run-1",
        graph_version: "1.3.0",
        phase: "COMPLETE",
        status: "COMPLETE",
        checkpoint_sequence: 7,
        projection_fingerprint: "6".repeat(64),
        observed_at: "2026-10-14T10:01:00Z",
        scope: "LATEST_DURABLE_PROJECTION",
      },
    ],
    checkpoints_truncated: false,
    audit: {
      status: "COMPLETE",
      complete: true,
      scope: "DISPLAYED_MODEL_CALLS",
      expected_event_count: 4,
      observed_event_count: 4,
      missing_event_count: 0,
      duplicate_event_count: 0,
      requirements: [
        {
          model_call_id: "call-success",
          event_type: "model.call_started",
          status: "PRESENT",
          observed_sequences: [10],
        },
        {
          model_call_id: "call-success",
          event_type: "model.call_finished",
          status: "PRESENT",
          observed_sequences: [11],
        },
        {
          model_call_id: "call-timeout",
          event_type: "model.call_started",
          status: "PRESENT",
          observed_sequences: [12],
        },
        {
          model_call_id: "call-timeout",
          event_type: "model.call_finished",
          status: "PRESENT",
          observed_sequences: [13],
        },
      ],
      rules_version: "1.0.0",
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("platform observability parsing", () => {
  it("parses exact traces, checkpoint projections, usage, and completeness", () => {
    const parsed = parsePlatformObservability(response());
    expect(parsed.modelCalls[0]?.tokenUsage?.totalTokens).toBe(120);
    expect(parsed.modelCalls[1]?.meteringUnavailableReason).toBe(
      "CALL_FAILED_BEFORE_METERING",
    );
    expect(parsed.checkpoints[0]?.checkpointSequence).toBe(7);
    expect(parsed.audit.complete).toBe(true);
  });

  it("accepts a pending call and a partial bounded response", () => {
    const value = response();
    const pending = value.model_calls[0]!;
    Object.assign(pending, {
      status: "STARTED",
      completed_at: null,
      duration_ms: null,
      token_usage: null,
      cost: null,
      response_hash: null,
    });
    value.model_calls = [pending];
    value.model_calls_truncated = true;
    value.usage = {
      call_count: 1,
      metered_call_count: 0,
      unavailable_call_count: 0,
      pending_call_count: 1,
      statuses: {
        started: 1,
        succeeded: 0,
        failed: 0,
        timed_out: 0,
        refused: 0,
      },
      tokens: {
        input_tokens: 0,
        output_tokens: 0,
        cached_input_tokens: 0,
        reasoning_tokens: 0,
        total_tokens: 0,
      },
      costs: [],
    };
    value.audit = {
      ...value.audit,
      status: "PARTIAL",
      complete: false,
      expected_event_count: 1,
      observed_event_count: 1,
      requirements: [value.audit.requirements[0]!],
    };
    const parsed = parsePlatformObservability(value);
    expect(parsed.modelCalls[0]?.status).toBe("STARTED");
    expect(parsed.audit.status).toBe("PARTIAL");
  });

  it("accepts explicit missing and duplicate audit requirements", () => {
    const value = response();
    value.audit.status = "INCOMPLETE";
    value.audit.complete = false;
    value.audit.observed_event_count = 4;
    value.audit.missing_event_count = 1;
    value.audit.duplicate_event_count = 1;
    value.audit.requirements[0]!.status = "MISSING";
    value.audit.requirements[0]!.observed_sequences = [];
    value.audit.requirements[1]!.status = "DUPLICATE";
    value.audit.requirements[1]!.observed_sequences = [11, 14];
    expect(parsePlatformObservability(value).audit.status).toBe("INCOMPLETE");
  });

  it.each([
    ["root", (value: ReturnType<typeof response>) => value as unknown, []],
    [
      "model array",
      (value: ReturnType<typeof response>) => value,
      { ...response(), model_calls: null },
    ],
    [
      "bad status",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.status = "UNKNOWN"),
    ],
    [
      "empty string",
      (value: ReturnType<typeof response>) => (value.model_calls[0]!.node = ""),
    ],
    [
      "bad timestamp",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.started_at = "bad"),
    ],
    [
      "bad hash",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.request_hash = "bad"),
    ],
    [
      "bad integer",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.attempt = -1),
    ],
    [
      "token arithmetic",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.token_usage!.total_tokens = 121),
    ],
    [
      "cached tokens",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.token_usage!.cached_input_tokens = 101),
    ],
    [
      "reasoning tokens",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.token_usage!.reasoning_tokens = 21),
    ],
    [
      "currency",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.cost!.currency = "usd"),
    ],
    [
      "started terminal metadata",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.status = "STARTED"),
    ],
    [
      "terminal completion",
      (value: ReturnType<typeof response>) =>
        ((
          value.model_calls[0]! as { completed_at: string | null }
        ).completed_at = null),
    ],
    [
      "time order",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.completed_at = "2026-10-14T09:00:00Z"),
    ],
    [
      "duration binding",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.duration_ms = 1),
    ],
    [
      "metering pair",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.cost = null),
    ],
    [
      "availability xor",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.metering_unavailable_reason = "NONE"),
    ],
    [
      "success failure",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.failure_code = "bad"),
    ],
    [
      "success response",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[0]!.response_hash = null),
    ],
    [
      "failure missing",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[1]!.failure_code = null),
    ],
    [
      "duplicate calls",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[1]!.id = "call-success"),
    ],
    [
      "call order",
      (value: ReturnType<typeof response>) =>
        (value.model_calls[1]!.started_at = "2026-10-14T11:00:00Z"),
    ],
    [
      "usage call count",
      (value: ReturnType<typeof response>) => (value.usage.call_count = 3),
    ],
    [
      "usage status",
      (value: ReturnType<typeof response>) =>
        (value.usage.statuses.succeeded = 0),
    ],
    [
      "usage pending",
      (value: ReturnType<typeof response>) =>
        (value.usage.pending_call_count = 1),
    ],
    [
      "usage metered",
      (value: ReturnType<typeof response>) =>
        (value.usage.metered_call_count = 0),
    ],
    [
      "usage unavailable",
      (value: ReturnType<typeof response>) =>
        (value.usage.unavailable_call_count = 0),
    ],
    [
      "usage token",
      (value: ReturnType<typeof response>) =>
        (value.usage.tokens.input_tokens = 99),
    ],
    [
      "duplicate currency",
      (value: ReturnType<typeof response>) =>
        value.usage.costs.push({ ...value.usage.costs[0]! }),
    ],
    [
      "wrong currency total",
      (value: ReturnType<typeof response>) =>
        (value.usage.costs[0]!.amount_nanounits = 1),
    ],
    [
      "aggregate currency",
      (value: ReturnType<typeof response>) =>
        (value.usage.costs[0]!.currency = "usd"),
    ],
    [
      "aggregate cost shape",
      (value: ReturnType<typeof response>) =>
        ((value.usage as { costs: unknown }).costs = null),
    ],
    [
      "checkpoint scope",
      (value: ReturnType<typeof response>) =>
        (value.checkpoints[0]!.scope = "OTHER"),
    ],
    [
      "checkpoint duplicate",
      (value: ReturnType<typeof response>) =>
        value.checkpoints.push({ ...value.checkpoints[0]! }),
    ],
    [
      "checkpoint order",
      (value: ReturnType<typeof response>) =>
        value.checkpoints.push({
          ...value.checkpoints[0]!,
          workflow_run_id: "run-2",
          observed_at: "2026-10-14T11:00:00Z",
        }),
    ],
    [
      "audit type",
      (value: ReturnType<typeof response>) =>
        (value.audit.requirements[0]!.event_type = "other"),
    ],
    [
      "audit requirements shape",
      (value: ReturnType<typeof response>) =>
        ((value.audit as { requirements: unknown }).requirements = null),
    ],
    [
      "audit status",
      (value: ReturnType<typeof response>) =>
        (value.audit.requirements[0]!.status = "OTHER"),
    ],
    [
      "audit sequence shape",
      (value: ReturnType<typeof response>) =>
        (value.audit.requirements[0]!.observed_sequences = [10, 10]),
    ],
    [
      "audit missing shape",
      (value: ReturnType<typeof response>) =>
        (value.audit.requirements[0]!.status = "MISSING"),
    ],
    [
      "audit present shape",
      (value: ReturnType<typeof response>) =>
        (value.audit.requirements[0]!.observed_sequences = []),
    ],
    [
      "audit duplicate shape",
      (value: ReturnType<typeof response>) =>
        (value.audit.requirements[0]!.status = "DUPLICATE"),
    ],
    [
      "audit keys",
      (value: ReturnType<typeof response>) =>
        (value.audit.requirements[0]!.model_call_id = "other"),
    ],
    [
      "audit expected count",
      (value: ReturnType<typeof response>) =>
        (value.audit.expected_event_count = 3),
    ],
    [
      "audit observed count",
      (value: ReturnType<typeof response>) =>
        (value.audit.observed_event_count = 3),
    ],
    [
      "audit missing count",
      (value: ReturnType<typeof response>) =>
        (value.audit.missing_event_count = 1),
    ],
    [
      "audit duplicate count",
      (value: ReturnType<typeof response>) =>
        (value.audit.duplicate_event_count = 1),
    ],
    [
      "audit complete",
      (value: ReturnType<typeof response>) => (value.audit.complete = false),
    ],
    [
      "audit decision",
      (value: ReturnType<typeof response>) => (value.audit.status = "PARTIAL"),
    ],
    [
      "audit scope",
      (value: ReturnType<typeof response>) => (value.audit.scope = "OTHER"),
    ],
    [
      "audit rules",
      (value: ReturnType<typeof response>) =>
        (value.audit.rules_version = "2.0.0"),
    ],
    [
      "checkpoint flag",
      (value: ReturnType<typeof response>) =>
        ((value as { checkpoints_truncated: unknown }).checkpoints_truncated =
          "yes"),
    ],
  ])("rejects invalid contract: %s", (...args: unknown[]) => {
    const [, mutate, replacement] = args as [
      string,
      (value: ReturnType<typeof response>) => unknown,
      unknown?,
    ];
    const value = response();
    mutate(value);
    expect(() =>
      parsePlatformObservability(
        replacement === undefined ? value : replacement,
      ),
    ).toThrow("invalid platform observability response");
  });

  it("loads with authenticated no-store semantics and rejects HTTP failures", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(response()), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await loadPlatformObservability("incident/a")).audit.complete).toBe(
      true,
    );
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      "incident%2Fa/platform-observability",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      cache: "no-store",
      credentials: "include",
    });
    await expect(loadPlatformObservability("incident/a")).rejects.toThrow(
      "Platform observability request failed (409)",
    );
  });
});
