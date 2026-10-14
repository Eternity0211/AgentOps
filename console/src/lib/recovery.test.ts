import { afterEach, describe, expect, it, vi } from "vitest";

import { loadRecovery, parseRecovery } from "./recovery";

const HASH = "a".repeat(64);

function response() {
  return {
    execution: {
      id: "execution-1",
      action: "rollback_service",
      approval_id: "approval-1",
      actor_id: "operator-1",
      status: "SUCCEEDED",
      version: 2,
      service: "orders",
      environment: "PRODUCTION",
      target_reference: "simulator-orders",
      expected_current_version: "2.0.0",
      stable_version: "1.0.0",
      before: {
        artifact_id: "before-artifact",
        content_hash: HASH,
        deployed_version: "2.0.0",
        observed_at: "2026-10-14T09:59:59Z",
      },
      after: {
        artifact_id: "after-artifact",
        content_hash: "b".repeat(64),
        deployed_version: "1.0.0",
        observed_at: "2026-10-14T10:00:30Z",
      },
      started_at: "2026-10-14T10:00:00Z",
      completed_at: "2026-10-14T10:01:00Z",
      failure_code: null,
      proposal_fingerprint: "c".repeat(64),
      policy_decision_fingerprint: "d".repeat(64),
      execution_fingerprint: "e".repeat(64),
      schema_version: "1.0.0",
    },
    verification: {
      id: "decision-1",
      observation_id: "observation-1",
      scenario: "RELEASE_HTTP_500",
      outcome: "PASS",
      reasons: [],
      service: "orders",
      environment: "PRODUCTION",
      expected_stable_version: "1.0.0",
      window_started_at: "2026-10-14T10:02:00Z",
      window_ended_at: "2026-10-14T10:03:00Z",
      window_duration_seconds: 60,
      sample_count: 3,
      first_sample: {
        observed_at: "2026-10-14T10:02:00Z",
        error_rate_basis_points: 25,
        p95_latency_ms: 200,
        health_endpoint_healthy: true,
        deployed_version: "1.0.0",
        new_alert_count: 0,
      },
      last_sample: {
        observed_at: "2026-10-14T10:03:00Z",
        error_rate_basis_points: 10,
        p95_latency_ms: 150,
        health_endpoint_healthy: true,
        deployed_version: "1.0.0",
        new_alert_count: 0,
      },
      evidence: {
        error_rate: "evidence-error",
        p95_latency: "evidence-p95",
        health_endpoint: "evidence-health",
        deployed_version: "evidence-version",
        new_alerts: "evidence-alerts",
      },
      collected_at: "2026-10-14T10:03:01Z",
      expires_at: "2026-10-14T11:03:01Z",
      evaluated_at: "2026-10-14T10:03:02Z",
      criteria_fingerprint: "f".repeat(64),
      observation_fingerprint: "1".repeat(64),
      execution_fingerprint: "e".repeat(64),
      input_fingerprint: "2".repeat(64),
      decision_fingerprint: "3".repeat(64),
      rules_version: "1.0.0",
      schema_version: "1.0.0",
    },
    route: {
      status: "CLOSED",
      final_state: "CLOSED",
      transitions: [
        {
          prior_state: "VERIFYING",
          new_state: "RESOLVED",
          prior_version: 5,
          new_version: 6,
          reason: "verification passed",
          actor_id: "operator-1",
          correlation_id: "correlation-1",
          causation_id: "decision-1",
          occurred_at: "2026-10-14T10:03:03Z",
        },
        {
          prior_state: "RESOLVED",
          new_state: "CLOSED",
          prior_version: 6,
          new_version: 7,
          reason: "verification passed",
          actor_id: "operator-1",
          correlation_id: "correlation-1",
          causation_id: "decision-1",
          occurred_at: "2026-10-14T10:03:03Z",
        },
      ],
    },
    compensation: {
      eligible: false,
      separately_authorized: false,
      status: "FORBIDDEN_FOR_ROLLBACK_SERVICE",
      detail: "Failed verification routes safely.",
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("recovery contract", () => {
  it("strictly parses the execution, verifier signals, route, and compensation boundary", () => {
    const parsed = parseRecovery(response());
    expect(parsed.execution?.before.deployedVersion).toBe("2.0.0");
    expect(parsed.execution?.after?.deployedVersion).toBe("1.0.0");
    expect(parsed.verification?.firstSample.errorRateBasisPoints).toBe(25);
    expect(parsed.route?.transitions).toHaveLength(2);
    expect(parsed.compensation.eligible).toBe(false);
  });

  it("accepts an incident with no execution and the explicit non-compensation boundary", () => {
    const value = response();
    value.execution = null as never;
    value.verification = null as never;
    value.route = null as never;
    expect(parseRecovery(value).execution).toBeNull();
  });

  it("accepts valid started, failed, and route-pending states", () => {
    const started = response();
    started.execution.status = "STARTED";
    started.execution.version = 1;
    started.execution.completed_at = null as never;
    started.execution.after = null as never;
    started.verification = null as never;
    started.route = null as never;
    expect(parseRecovery(started).execution?.status).toBe("STARTED");

    const failed = response();
    failed.execution.status = "FAILED";
    failed.execution.after = null as never;
    failed.execution.failure_code = "ADAPTER_REJECTED" as never;
    failed.verification = null as never;
    failed.route = null as never;
    expect(parseRecovery(failed).execution?.status).toBe("FAILED");

    const pending = response();
    pending.route.status = "PENDING";
    pending.route.final_state = null as never;
    pending.route.transitions = [];
    expect(parseRecovery(pending).route?.status).toBe("PENDING");

    const verificationFailed = response();
    verificationFailed.verification.outcome = "FAIL";
    verificationFailed.verification.reasons = [
      "P95_LATENCY_ABOVE_LIMIT",
    ] as never;
    expect(parseRecovery(verificationFailed).verification?.outcome).toBe(
      "FAIL",
    );
  });

  it.each([
    [
      "execution hash",
      (value: ReturnType<typeof response>) => {
        value.execution.execution_fingerprint = "bad";
      },
    ],
    [
      "cross-service verifier",
      (value: ReturnType<typeof response>) => {
        value.verification.service = "payments";
      },
    ],
    [
      "window mismatch",
      (value: ReturnType<typeof response>) => {
        value.verification.window_duration_seconds = 30;
      },
    ],
    [
      "duplicate evidence",
      (value: ReturnType<typeof response>) => {
        value.verification.evidence.new_alerts = "evidence-error";
      },
    ],
    [
      "unbound route",
      (value: ReturnType<typeof response>) => {
        value.route.transitions[0]!.causation_id = "other";
      },
    ],
    [
      "invented compensation",
      (value: ReturnType<typeof response>) => {
        value.compensation.eligible = true;
      },
    ],
  ])("rejects %s", (_label, mutate) => {
    const value = response();
    mutate(value);
    expect(() => parseRecovery(value)).toThrow("invalid recovery response");
  });

  it.each([
    [
      "non-object",
      (value: ReturnType<typeof response>) => value as never,
      null,
    ],
    [
      "empty identity",
      (value: ReturnType<typeof response>) => {
        value.execution.id = "";
      },
      undefined,
    ],
    [
      "bad instant",
      (value: ReturnType<typeof response>) => {
        value.execution.started_at = "not-a-time";
      },
      undefined,
    ],
    [
      "bad integer",
      (value: ReturnType<typeof response>) => {
        value.execution.version = 0;
      },
      undefined,
    ],
    [
      "bad status",
      (value: ReturnType<typeof response>) => {
        value.execution.status = "BROKEN";
      },
      undefined,
    ],
    [
      "bad action",
      (value: ReturnType<typeof response>) => {
        value.execution.action = "shell";
      },
      undefined,
    ],
    [
      "wrong before version",
      (value: ReturnType<typeof response>) => {
        value.execution.before.deployed_version = "9.0.0";
      },
      undefined,
    ],
    [
      "late before snapshot",
      (value: ReturnType<typeof response>) => {
        value.execution.before.observed_at = "2026-10-14T10:00:01Z";
      },
      undefined,
    ],
    [
      "missing completion",
      (value: ReturnType<typeof response>) => {
        value.execution.completed_at = null as never;
      },
      undefined,
    ],
    [
      "regressed completion",
      (value: ReturnType<typeof response>) => {
        value.execution.completed_at = "2026-10-14T09:00:00Z";
      },
      undefined,
    ],
    [
      "missing success snapshot",
      (value: ReturnType<typeof response>) => {
        value.execution.after = null as never;
      },
      undefined,
    ],
    [
      "wrong success version",
      (value: ReturnType<typeof response>) => {
        value.execution.after.deployed_version = "3.0.0";
      },
      undefined,
    ],
    [
      "success failure code",
      (value: ReturnType<typeof response>) => {
        value.execution.failure_code = "FAILED" as never;
      },
      undefined,
    ],
    [
      "invalid health flag",
      (value: ReturnType<typeof response>) => {
        value.verification.first_sample.health_endpoint_healthy =
          "yes" as never;
      },
      undefined,
    ],
    [
      "bad outcome",
      (value: ReturnType<typeof response>) => {
        value.verification.outcome = "UNKNOWN";
      },
      undefined,
    ],
    [
      "bad reasons",
      (value: ReturnType<typeof response>) => {
        value.verification.reasons = null as never;
      },
      undefined,
    ],
    [
      "bad route status",
      (value: ReturnType<typeof response>) => {
        value.route.status = "UNKNOWN";
      },
      undefined,
    ],
    [
      "bad route collection",
      (value: ReturnType<typeof response>) => {
        value.route.transitions = null as never;
      },
      undefined,
    ],
    [
      "route version step",
      (value: ReturnType<typeof response>) => {
        value.route.transitions[0]!.new_version = 9;
      },
      undefined,
    ],
    [
      "route predates decision",
      (value: ReturnType<typeof response>) => {
        value.route.transitions[0]!.occurred_at = "2026-10-14T10:03:01Z";
      },
      undefined,
    ],
    [
      "closed route empty",
      (value: ReturnType<typeof response>) => {
        value.route.transitions = [];
      },
      undefined,
    ],
    [
      "route final mismatch",
      (value: ReturnType<typeof response>) => {
        value.route.final_state = "RESOLVED";
      },
      undefined,
    ],
    [
      "route discontinuity",
      (value: ReturnType<typeof response>) => {
        value.route.transitions[1]!.prior_version = 8;
      },
      undefined,
    ],
    [
      "orphan verification",
      (value: ReturnType<typeof response>) => {
        value.execution = null as never;
      },
      undefined,
    ],
    [
      "route without verification",
      (value: ReturnType<typeof response>) => {
        value.verification = null as never;
      },
      undefined,
    ],
    [
      "verification without route",
      (value: ReturnType<typeof response>) => {
        value.route = null as never;
      },
      undefined,
    ],
  ])("rejects malformed invariant: %s", (_label, mutate, replacement) => {
    const value = response();
    mutate(value);
    expect(() => parseRecovery(replacement === null ? null : value)).toThrow(
      "invalid recovery response",
    );
  });

  it("loads with authenticated no-store semantics and rejects HTTP failures", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(response()), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await loadRecovery("incident/a")).verification?.outcome).toBe(
      "PASS",
    );
    expect(fetchMock.mock.calls[0]?.[0]).toContain("incident%2Fa/recovery");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      cache: "no-store",
      credentials: "include",
    });
    await expect(loadRecovery("incident/a")).rejects.toThrow(
      "Recovery request failed (409)",
    );
  });
});
