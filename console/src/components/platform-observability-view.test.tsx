import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PlatformObservability } from "@/lib/platform-observability";

import { PlatformObservabilityView } from "./platform-observability-view";

const platform: PlatformObservability = {
  modelCalls: [
    {
      id: "call-1",
      workflowRunId: "run-1",
      node: "diagnosis.hypothesis",
      attempt: 1,
      promptId: "prompt-1",
      promptVersion: "1.0.0",
      promptFingerprint: "1".repeat(64),
      provider: "mock",
      model: "deterministic",
      status: "SUCCEEDED",
      startedAt: "2026-10-14T10:00:00Z",
      completedAt: "2026-10-14T10:00:02Z",
      durationMs: 2000,
      tokenUsage: {
        inputTokens: 100,
        outputTokens: 20,
        cachedInputTokens: 10,
        reasoningTokens: 5,
        totalTokens: 120,
      },
      cost: {
        amountNanounits: 12_345,
        currency: "USD",
        source: "RATE_CARD_CALCULATED",
        rateCardVersion: "1.0.0",
      },
      meteringUnavailableReason: null,
      failureCode: null,
      correlationId: "correlation-1",
      causationId: "node-1",
      requestHash: "2".repeat(64),
      responseHash: "3".repeat(64),
      inputSchemaVersion: "1.0.0",
      outputSchemaVersion: "1.0.0",
      schemaVersion: "1.0.0",
    },
  ],
  modelCallsTruncated: false,
  usage: {
    callCount: 1,
    meteredCallCount: 1,
    unavailableCallCount: 0,
    pendingCallCount: 0,
    statuses: { started: 0, succeeded: 1, failed: 0, timedOut: 0, refused: 0 },
    tokens: {
      inputTokens: 100,
      outputTokens: 20,
      cachedInputTokens: 10,
      reasoningTokens: 5,
      totalTokens: 120,
    },
    costs: [{ currency: "USD", amountNanounits: 12_345 }],
  },
  checkpoints: [
    {
      workflowRunId: "run-1",
      graphVersion: "1.3.0",
      phase: "COMPLETE",
      status: "COMPLETE",
      checkpointSequence: 7,
      projectionFingerprint: "4".repeat(64),
      observedAt: "2026-10-14T10:01:00Z",
      scope: "LATEST_DURABLE_PROJECTION",
    },
  ],
  checkpointsTruncated: false,
  audit: {
    status: "COMPLETE",
    complete: true,
    scope: "DISPLAYED_MODEL_CALLS",
    expectedEventCount: 2,
    observedEventCount: 2,
    missingEventCount: 0,
    duplicateEventCount: 0,
    requirements: [
      {
        modelCallId: "call-1",
        eventType: "model.call_started",
        status: "PRESENT",
        observedSequences: [10],
      },
      {
        modelCallId: "call-1",
        eventType: "model.call_finished",
        status: "PRESENT",
        observedSequences: [11],
      },
    ],
    rulesVersion: "1.0.0",
  },
};

describe("PlatformObservabilityView", () => {
  it("shows exact call usage, trace bindings, checkpoint state, and backend audit decision", () => {
    render(<PlatformObservabilityView platform={platform} />);
    expect(
      screen.getByRole("heading", { name: "Agent platform observability" }),
    ).toBeVisible();
    expect(screen.getByLabelText("Model usage totals")).toHaveTextContent(
      "120",
    );
    expect(screen.getAllByText("0.000012345 USD")).toHaveLength(2);
    expect(screen.getByText("diagnosis.hypothesis")).toBeVisible();
    expect(screen.getByText(/2000 ms/)).toBeVisible();
    expect(screen.getByText(/Checkpoint 7/)).toBeVisible();
    const audit = screen.getByLabelText("Audit completeness");
    expect(
      within(audit).getByRole("heading", { name: "COMPLETE" }),
    ).toBeVisible();
    expect(within(audit).getByText(/2 observed \/ 2 expected/)).toBeVisible();
  });

  it("renders bounded warnings, failures, unavailable metering, and missing audit", () => {
    render(
      <PlatformObservabilityView
        platform={{
          ...platform,
          modelCallsTruncated: true,
          checkpointsTruncated: true,
          modelCalls: [
            {
              ...platform.modelCalls[0]!,
              status: "TIMED_OUT",
              tokenUsage: null,
              cost: null,
              meteringUnavailableReason: "CALL_FAILED_BEFORE_METERING",
              failureCode: "provider_timeout",
              responseHash: null,
            },
            {
              ...platform.modelCalls[0]!,
              id: "call-pending",
              status: "STARTED",
              completedAt: null,
              durationMs: null,
              tokenUsage: null,
              cost: null,
              meteringUnavailableReason: null,
              responseHash: null,
            },
          ],
          audit: {
            ...platform.audit,
            status: "PARTIAL",
            complete: false,
            observedEventCount: 0,
            missingEventCount: 2,
            requirements: platform.audit.requirements.map((item) => ({
              ...item,
              status: "MISSING" as const,
              observedSequences: [],
            })),
          },
        }}
      />,
    );
    expect(screen.getByText(/Older model calls are omitted/)).toBeVisible();
    expect(screen.getByText(/Older run projections are omitted/)).toBeVisible();
    expect(screen.getByText("CALL FAILED BEFORE METERING")).toBeVisible();
    expect(screen.getByText(/Failure: provider_timeout/)).toBeVisible();
    expect(screen.getAllByText("No sequence")).toHaveLength(2);
  });

  it("renders empty traces, checkpoints, costs, and audit expectations", () => {
    render(
      <PlatformObservabilityView
        platform={{
          ...platform,
          modelCalls: [],
          usage: {
            ...platform.usage,
            callCount: 0,
            meteredCallCount: 0,
            costs: [],
            tokens: {
              inputTokens: 0,
              outputTokens: 0,
              cachedInputTokens: 0,
              reasoningTokens: 0,
              totalTokens: 0,
            },
          },
          checkpoints: [],
          audit: {
            ...platform.audit,
            expectedEventCount: 0,
            observedEventCount: 0,
            requirements: [],
          },
        }}
      />,
    );
    expect(screen.getByText("Not available")).toBeVisible();
    expect(screen.getByText(/No model-call trace/)).toBeVisible();
    expect(screen.getByText(/No durable Diagnosis checkpoint/)).toBeVisible();
    expect(
      screen.getByText(/No model-call audit event is expected/),
    ).toBeVisible();
  });
});
