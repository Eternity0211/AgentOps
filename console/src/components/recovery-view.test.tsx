import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RecoveryResult } from "@/lib/recovery";

import { RecoveryView } from "./recovery-view";

const recovery: RecoveryResult = {
  execution: {
    id: "execution-1",
    action: "rollback_service",
    approvalId: "approval-1",
    actorId: "operator-1",
    status: "SUCCEEDED",
    version: 2,
    service: "orders",
    environment: "PRODUCTION",
    targetReference: "simulator-orders",
    expectedCurrentVersion: "2.0.0",
    stableVersion: "1.0.0",
    before: {
      artifactId: "before-artifact",
      contentHash: "a".repeat(64),
      deployedVersion: "2.0.0",
      observedAt: "2026-10-14T09:59:59Z",
    },
    after: {
      artifactId: "after-artifact",
      contentHash: "b".repeat(64),
      deployedVersion: "1.0.0",
      observedAt: "2026-10-14T10:00:30Z",
    },
    startedAt: "2026-10-14T10:00:00Z",
    completedAt: "2026-10-14T10:01:00Z",
    failureCode: null,
    proposalFingerprint: "c".repeat(64),
    policyDecisionFingerprint: "d".repeat(64),
    executionFingerprint: "e".repeat(64),
    schemaVersion: "1.0.0",
  },
  verification: {
    id: "decision-1",
    observationId: "observation-1",
    scenario: "RELEASE_HTTP_500",
    outcome: "FAIL",
    reasons: ["P95_LATENCY_ABOVE_LIMIT"],
    service: "orders",
    environment: "PRODUCTION",
    expectedStableVersion: "1.0.0",
    windowStartedAt: "2026-10-14T10:02:00Z",
    windowEndedAt: "2026-10-14T10:03:00Z",
    windowDurationSeconds: 60,
    sampleCount: 3,
    firstSample: {
      observedAt: "2026-10-14T10:02:00Z",
      errorRateBasisPoints: 25,
      p95LatencyMs: 200,
      healthEndpointHealthy: true,
      deployedVersion: "1.0.0",
      newAlertCount: 0,
    },
    lastSample: {
      observedAt: "2026-10-14T10:03:00Z",
      errorRateBasisPoints: 50,
      p95LatencyMs: 501,
      healthEndpointHealthy: false,
      deployedVersion: "1.0.0",
      newAlertCount: 1,
    },
    evidence: {
      errorRate: "evidence-error",
      p95Latency: "evidence-p95",
      healthEndpoint: "evidence-health",
      deployedVersion: "evidence-version",
      newAlerts: "evidence-alerts",
    },
    collectedAt: "2026-10-14T10:03:01Z",
    expiresAt: "2026-10-14T11:03:01Z",
    evaluatedAt: "2026-10-14T10:03:02Z",
    criteriaFingerprint: "f".repeat(64),
    observationFingerprint: "1".repeat(64),
    executionFingerprint: "e".repeat(64),
    inputFingerprint: "2".repeat(64),
    decisionFingerprint: "3".repeat(64),
    rulesVersion: "1.0.0",
    schemaVersion: "1.0.0",
  },
  route: {
    status: "REDIAGNOSE",
    finalState: "INVESTIGATING",
    transitions: [
      {
        priorState: "VERIFYING",
        newState: "INVESTIGATING",
        priorVersion: 5,
        newVersion: 6,
        reason:
          "failed rollback verification; route=REDIAGNOSE; compensation=forbidden",
        actorId: "operator-1",
        correlationId: "correlation-1",
        causationId: "decision-1",
        occurredAt: "2026-10-14T10:03:03Z",
      },
    ],
  },
  compensation: {
    eligible: false,
    separatelyAuthorized: false,
    status: "FORBIDDEN_FOR_ROLLBACK_SERVICE",
    detail:
      "A failed verification routes to bounded re-diagnosis or human handoff.",
  },
};

describe("RecoveryView", () => {
  it("shows authoritative snapshots, five signals, evidence links, failure route, and compensation boundary", () => {
    render(<RecoveryView incidentId="incident-1" recovery={recovery} />);
    expect(
      screen.getByRole("heading", { name: "Execution and verification" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "rollback_service" }),
    ).toBeVisible();
    expect(
      screen.getByLabelText("Deployment version comparison"),
    ).toHaveTextContent("2.0.0");
    expect(
      screen.getByLabelText("Deployment version comparison"),
    ).toHaveTextContent("1.0.0");
    expect(screen.getByText("501 ms")).toBeVisible();
    expect(screen.getByText("P95 LATENCY ABOVE LIMIT")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "P95 latency: evidence-p95" }),
    ).toHaveAttribute("href", "#evidence-evidence-p95");
    expect(screen.getByRole("heading", { name: "REDIAGNOSE" })).toBeVisible();
    const boundary = screen.getByLabelText("Compensation authorization");
    expect(
      within(boundary).getByText(/FORBIDDEN FOR ROLLBACK SERVICE/),
    ).toBeVisible();
    expect(
      within(boundary).getByText(/No separate compensation authorization/),
    ).toBeVisible();
  });

  it("does not imply success before deterministic verification exists", () => {
    render(
      <RecoveryView
        incidentId="incident-1"
        recovery={{ ...recovery, verification: null, route: null }}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Verification not recorded" }),
    ).toBeVisible();
    expect(screen.getByText(/will not declare recovery/)).toBeVisible();
  });

  it("shows a failed execution without inventing an after snapshot", () => {
    render(
      <RecoveryView
        incidentId="incident-1"
        recovery={{
          ...recovery,
          execution: {
            ...recovery.execution!,
            status: "FAILED",
            after: null,
            failureCode: "ADAPTER_REJECTED",
          },
          verification: null,
          route: null,
        }}
      />,
    );
    expect(screen.getByText("No after snapshot")).toBeVisible();
    expect(screen.getByText("ADAPTER_REJECTED")).toBeVisible();
    expect(
      screen.getByText(/did not produce a completed deployment snapshot/),
    ).toBeVisible();
  });

  it("shows a passing verification whose lifecycle route is still pending", () => {
    render(
      <RecoveryView
        incidentId="incident-1"
        recovery={{
          ...recovery,
          verification: {
            ...recovery.verification!,
            outcome: "PASS",
            reasons: [],
          },
          route: { status: "PENDING", finalState: null, transitions: [] },
        }}
      />,
    );
    expect(screen.getByText("All configured checks passed")).toBeVisible();
    expect(screen.getByText("No failure reason was recorded.")).toBeVisible();
    expect(
      screen.getByText(
        "No post-verification lifecycle transition has been recorded yet.",
      ),
    ).toBeVisible();
  });

  it("renders an execution empty state", () => {
    render(
      <RecoveryView
        incidentId="incident-1"
        recovery={{
          ...recovery,
          execution: null,
          verification: null,
          route: null,
        }}
      />,
    );
    expect(
      screen.getByText(
        "No recovery execution has been recorded for this incident.",
      ),
    ).toBeVisible();
  });
});
