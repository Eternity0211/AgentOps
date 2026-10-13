import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadDiagnosis } from "./diagnosis";

function gate(overrides: Record<string, unknown> = {}) {
  return {
    outcome: "FAIL",
    reasons: [
      {
        code: "MISSING_EVIDENCE_DECLARED",
        detail: "Required evidence is missing.",
        evidence_ids: [],
      },
    ],
    evaluated_evidence_ids: ["evidence-1"],
    rules_version: "gate-v1",
    input_fingerprint: "a".repeat(64),
    decision_fingerprint: "b".repeat(64),
    evaluated_at: "2026-10-13T01:00:00Z",
    model_confidence_basis_points: 8100,
    schema_version: "1.0.0",
    ...overrides,
  };
}

function result(overrides: Record<string, unknown> = {}) {
  return {
    workflow_run_id: "run-1",
    model_call_id: "model-1",
    report_fingerprint: "c".repeat(64),
    produced_at: "2026-10-13T01:00:00Z",
    disposition: "CANDIDATES",
    candidates: [
      {
        candidate_id: "candidate-1",
        rank: 1,
        statement: "Connection pool exhaustion",
        supporting_evidence_ids: ["evidence-1"],
        counter_evidence_ids: ["evidence-2"],
        counter_evidence_treatment: "RESOLVED",
        counter_evidence_explanation: "The healthy shard uses another pool.",
        missing_evidence: ["Per-pod pool saturation"],
        uncertainty: "One pod lacks a trace sample.",
        confidence_basis_points: 8100,
        gate: gate(),
      },
    ],
    missing_evidence: ["Per-pod pool saturation"],
    explanation: "Ranked from two independent sources.",
    schema_version: "1.0.0",
    ...overrides,
  };
}

beforeEach(() => vi.unstubAllGlobals());

describe("loadDiagnosis", () => {
  it("strictly maps the evidence-bound report and gate", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ result: result() }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await expect(loadDiagnosis("incident / one")).resolves.toEqual(
      expect.objectContaining({
        disposition: "CANDIDATES",
        candidates: [
          expect.objectContaining({
            rank: 1,
            gate: expect.objectContaining({ outcome: "FAIL" }),
          }),
        ],
      }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/incidents/incident%20%2F%20one/diagnosis",
      expect.objectContaining({ cache: "no-store", credentials: "include" }),
    );
  });

  it("accepts an empty non-candidate result and nullable gate fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            result: result({
              disposition: "NEEDS_MORE_EVIDENCE",
              candidates: [],
              missing_evidence: [],
            }),
          }),
          { status: 200 },
        ),
      ),
    );
    await expect(loadDiagnosis("incident-1")).resolves.toEqual(
      expect.objectContaining({
        disposition: "NEEDS_MORE_EVIDENCE",
        candidates: [],
      }),
    );

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            result: result({
              candidates: [
                {
                  ...result().candidates[0],
                  counter_evidence_explanation: null,
                  gate: gate({
                    outcome: "PASS",
                    reasons: [],
                    model_confidence_basis_points: null,
                  }),
                },
              ],
            }),
          }),
          { status: 200 },
        ),
      ),
    );
    await expect(loadDiagnosis("incident-1")).resolves.toEqual(
      expect.objectContaining({
        candidates: [expect.objectContaining({ gate: expect.anything() })],
      }),
    );

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            result: result({
              candidates: [{ ...result().candidates[0], gate: null }],
            }),
          }),
          { status: 200 },
        ),
      ),
    );
    await expect(loadDiagnosis("incident-1")).resolves.toEqual(
      expect.objectContaining({
        candidates: [expect.objectContaining({ gate: null })],
      }),
    );
  });

  it("returns null and rejects transport or malformed responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response('{"result":null}')),
    );
    await expect(loadDiagnosis("incident-1")).resolves.toBeNull();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 409 })),
    );
    await expect(loadDiagnosis("incident-1")).rejects.toThrow(
      "Diagnosis request failed (409)",
    );

    const invalidValues = [
      null,
      [],
      { result: 1 },
      { result: result({ disposition: "UNKNOWN" }) },
      { result: result({ candidates: "bad" }) },
      { result: result({ disposition: "REFUSED" }) },
      {
        result: result({
          candidates: [{ ...result().candidates[0], rank: 2 }],
        }),
      },
      {
        result: result({
          candidates: [
            { ...result().candidates[0], supporting_evidence_ids: [] },
          ],
        }),
      },
      {
        result: result({
          candidates: [
            { ...result().candidates[0], counter_evidence_treatment: "BAD" },
          ],
        }),
      },
      {
        result: result({
          candidates: [
            { ...result().candidates[0], gate: gate({ outcome: "MAYBE" }) },
          ],
        }),
      },
      {
        result: result({
          candidates: [
            { ...result().candidates[0], gate: gate({ reasons: "bad" }) },
          ],
        }),
      },
      {
        result: result({
          candidates: [
            { ...result().candidates[0], gate: gate({ outcome: "PASS" }) },
          ],
        }),
      },
      { result: result({ produced_at: "not-time" }) },
      { result: result({ explanation: "" }) },
      { result: result({ missing_evidence: ["duplicate", "duplicate"] }) },
      {
        result: result({
          candidates: [
            { ...result().candidates[0], confidence_basis_points: 10001 },
          ],
        }),
      },
    ];
    for (const value of invalidValues) {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(JSON.stringify(value))),
      );
      await expect(loadDiagnosis("incident-1")).rejects.toThrow(
        "invalid diagnosis result response",
      );
    }
  });
});
