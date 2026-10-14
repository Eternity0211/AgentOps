import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApprovalRequestError,
  decideApproval,
  loadApproval,
  loadApprovals,
  parseApprovalDetail,
  parseApprovalSummary,
} from "./approvals";

function summary(overrides: Record<string, unknown> = {}) {
  return {
    id: "approval-1",
    incident_id: "incident-1",
    proposal_id: "proposal-1",
    proposal_version: 1,
    proposal_fingerprint: "a".repeat(64),
    policy_decision_fingerprint: "b".repeat(64),
    proposer_actor_id: "operator-1",
    risk_level: "HIGH",
    status: "PENDING",
    version: 1,
    requested_at: "2026-10-13T01:00:00Z",
    expires_at: "2026-10-13T01:30:00Z",
    decided_at: null,
    decided_by: null,
    decision_reason: null,
    expired: false,
    invalidated: false,
    separation_of_duties: {
      required: true,
      satisfied: true,
      code: "INDEPENDENT_APPROVER_PRESENT",
      detail: "The reviewer is independent.",
    },
    schema_version: "1.0.0",
    ...overrides,
  };
}

function proposal(version = 1) {
  return {
    schema_version: "1.0.0",
    proposal_id: "proposal-1",
    proposal_version: version,
    incident_id: "incident-1",
    candidate_id: "candidate-1",
    evidence_gate_input_fingerprint: "c".repeat(64),
    evidence_gate_decision_fingerprint: "d".repeat(64),
    action: "rollback_service",
    parameters: {
      service: "orders",
      introducing_deployment_evidence_id: "evidence-deploy",
    },
    prerequisites: { current_version_evidence_id: "evidence-current" },
    verification_conditions: {
      max_error_rate_basis_points: 100,
      max_p95_latency_ms: 500,
      stability_window_seconds: 300,
    },
    failure_handling: {
      route: "HUMAN_HANDOFF",
      max_rediagnosis_attempts: 0,
    },
    compensation_eligible: false,
    risk_assumptions: ["The current deployment is faulty."],
  };
}

function detail(revised = false) {
  return {
    approval: summary({ invalidated: revised }),
    proposal: proposal(),
    policy: {
      decision_id: "policy-1",
      policy_version: "1.0.0",
      outcome: "APPROVAL_REQUIRED",
      risk_level: "HIGH",
      reasons: [
        { code: "APPROVAL_REQUIRED", detail: "Human approval is required." },
      ],
      environment: "PRODUCTION",
      blast_radius: "SINGLE_SERVICE",
      maintenance_window: "ACTIVE",
      service: "orders",
      requester_roles: ["OPERATOR"],
      separation_of_duties_required: true,
      evaluated_at: "2026-10-13T01:00:00Z",
      approval_ttl_seconds: 1800,
      input_fingerprint: "e".repeat(64),
      decision_fingerprint: "f".repeat(64),
      schema_version: "1.0.0",
    },
    review_fingerprint: "1".repeat(64),
    replacement_proposal: revised ? proposal(2) : null,
    proposal_diff: revised
      ? [{ path: "$.proposal_version", before: 1, after: 2 }]
      : [],
    invalidation: revised
      ? {
          invalidated_by: "operator-1",
          invalidated_at: "2026-10-13T01:10:00Z",
          replacement_proposal_id: "proposal-1",
          replacement_proposal_version: 2,
          replacement_proposal_fingerprint: "2".repeat(64),
          schema_version: "1.0.0",
        }
      : null,
  };
}

beforeEach(() => vi.unstubAllGlobals());

describe("Approval API client", () => {
  it("parses pending, terminal, and revised verified records", () => {
    expect(parseApprovalSummary(summary()).status).toBe("PENDING");
    expect(
      parseApprovalSummary(
        summary({
          status: "APPROVED",
          version: 2,
          decided_at: "2026-10-13T01:05:00Z",
          decided_by: "approver-1",
          decision_reason: "Reviewed.",
        }),
      ).decidedBy,
    ).toBe("approver-1");
    expect(parseApprovalDetail(detail()).replacementProposal).toBeNull();
    expect(parseApprovalDetail(detail(true)).proposalDiff).toEqual([
      { path: "$.proposal_version", before: 1, after: 2 },
    ]);
  });

  it("rejects malformed summaries, policy, proposal, diff, and invalidation", () => {
    const badSummaries = [
      null,
      [],
      summary({ id: "" }),
      summary({ proposal_version: 0 }),
      summary({ proposal_fingerprint: "bad" }),
      summary({ risk_level: "EXTREME" }),
      summary({ status: "UNKNOWN" }),
      summary({ version: 0 }),
      summary({ requested_at: "bad" }),
      summary({ decided_at: 1 }),
      summary({ decided_at: "bad" }),
      summary({ decided_by: 1 }),
      summary({ decision_reason: 1 }),
      summary({ expired: "no" }),
      summary({ invalidated: "no" }),
      summary({ schema_version: "" }),
      summary({ separation_of_duties: null }),
      summary({ separation_of_duties: { required: "yes" } }),
      summary({
        separation_of_duties: {
          required: true,
          satisfied: true,
          code: "OK",
          detail: "",
        },
      }),
    ];
    for (const item of badSummaries) {
      expect(() => parseApprovalSummary(item)).toThrow();
    }

    const badDetails = [
      null,
      { ...detail(), review_fingerprint: "bad" },
      { ...detail(), proposal_diff: "bad" },
      { ...detail(), proposal: { ...proposal(), action: "shell" } },
      { ...detail(), proposal_diff: [{ path: "bad" }] },
      { ...detail(), policy: { ...detail().policy, reasons: "bad" } },
      {
        ...detail(),
        policy: {
          ...detail().policy,
          reasons: [{ code: "", detail: "bad" }],
        },
      },
      { ...detail(), policy: { ...detail().policy, approval_ttl_seconds: 1 } },
      { ...detail(true), invalidation: { invalidated_by: "" } },
      { ...detail(), replacement_proposal: proposal(2) },
      { ...detail(true), replacement_proposal: null },
    ];
    for (const item of badDetails) {
      expect(() => parseApprovalDetail(item)).toThrow();
    }
  });

  it("loads list/detail with filters and submits typed decisions", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ items: [summary()], next_cursor: "next" }),
        ),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(detail())))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ approval: summary({ status: "REJECTED" }) }),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    await expect(loadApprovals("PENDING", "cursor-1")).resolves.toEqual(
      expect.objectContaining({ nextCursor: "next" }),
    );
    await expect(loadApproval("approval / 1")).resolves.toEqual(
      expect.objectContaining({ reviewFingerprint: "1".repeat(64) }),
    );
    await expect(
      decideApproval("approval / 1", "reject", 1, "Scope needs revision."),
    ).resolves.toEqual(expect.objectContaining({ status: "REJECTED" }));
    expect(fetchMock.mock.calls[0]![0]).toContain(
      "status=PENDING&cursor=cursor-1",
    );
    expect(fetchMock.mock.calls[1]![0]).toContain("approval%20%2F%201");
    expect(fetchMock.mock.calls[2]![1]).toEqual(
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("handles unfiltered pages, problem details, and malformed responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ items: [], next_cursor: null })),
        ),
    );
    await expect(loadApprovals()).resolves.toEqual({
      items: [],
      nextCursor: null,
    });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Approval changed." }), {
          status: 409,
          headers: { "X-Request-ID": "request-1" },
        }),
      ),
    );
    await expect(loadApproval("approval-1")).rejects.toEqual(
      new ApprovalRequestError(409, "Approval changed.", "request-1"),
    );

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not-json", { status: 500 })),
    );
    await expect(loadApproval("approval-1")).rejects.toThrow(
      "Approval detail request failed (500)",
    );

    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: 42 }), { status: 503 }),
        ),
    );
    await expect(loadApproval("approval-1")).rejects.toThrow(
      "Approval detail request failed (503)",
    );

    for (const response of [
      {},
      { items: "bad", next_cursor: null },
      { items: [], next_cursor: 1 },
    ]) {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(JSON.stringify(response))),
      );
      await expect(loadApprovals()).rejects.toThrow(
        "invalid Approval page response",
      );
    }
  });
});
