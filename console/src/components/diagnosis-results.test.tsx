import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DiagnosisResult } from "@/lib/diagnosis";
import { DiagnosisResults } from "./diagnosis-results";

const base: DiagnosisResult = {
  workflowRunId: "run-1",
  modelCallId: "model-1",
  reportFingerprint: "a".repeat(64),
  producedAt: "2026-10-13T01:00:00Z",
  disposition: "CANDIDATES",
  candidates: [
    {
      candidateId: "candidate-1",
      rank: 1,
      statement: "Connection pool exhaustion",
      supportingEvidenceIds: ["evidence-1"],
      counterEvidenceIds: ["evidence-2"],
      counterEvidenceTreatment: "UNRESOLVED",
      counterEvidenceExplanation: "Healthy canary remains unexplained.",
      missingEvidence: ["Pool saturation by pod"],
      uncertainty: "One trace window is missing.",
      confidenceBasisPoints: 8125,
      gate: {
        outcome: "FAIL",
        reasons: [
          {
            code: "COUNTER_EVIDENCE_UNRESOLVED",
            detail: "Counter-evidence remains.",
            evidenceIds: ["evidence-2"],
          },
        ],
        evaluatedEvidenceIds: ["evidence-1", "evidence-2"],
        rulesVersion: "gate-v1",
        inputFingerprint: "b".repeat(64),
        decisionFingerprint: "c".repeat(64),
        evaluatedAt: "2026-10-13T01:01:00Z",
        modelConfidenceBasisPoints: 8125,
        schemaVersion: "1.0.0",
      },
    },
  ],
  missingEvidence: ["Pool saturation by pod"],
  explanation: "Evidence-bound ranked result.",
  schemaVersion: "1.0.0",
};

describe("DiagnosisResults", () => {
  it("shows ranked evidence, uncertainty and deterministic gate detail", () => {
    render(<DiagnosisResults result={base} />);
    expect(
      screen.getByRole("heading", { name: "Ranked diagnosis" }),
    ).toBeVisible();
    expect(screen.getByText("81.25% model confidence")).toBeVisible();
    expect(screen.getByText(/non-authoritative/)).toBeVisible();
    expect(screen.getByRole("link", { name: "evidence-1" })).toHaveAttribute(
      "href",
      "#evidence-evidence-1",
    );
    expect(screen.getByText("FAIL")).toBeVisible();
    expect(screen.getByText(/Counter-evidence remains/)).toBeVisible();
    expect(screen.getByText(/One trace window is missing/)).toBeVisible();
  });

  it("shows empty, non-candidate, unevaluated and passing states", () => {
    const { rerender } = render(<DiagnosisResults result={null} />);
    expect(
      screen.getByText("No verified diagnosis report has been recorded."),
    ).toBeVisible();
    rerender(
      <DiagnosisResults
        result={{
          ...base,
          disposition: "REFUSED",
          candidates: [],
          missingEvidence: [],
        }}
      />,
    );
    expect(screen.getByText(/No root-cause candidate/)).toBeVisible();
    rerender(
      <DiagnosisResults
        result={{
          ...base,
          candidates: [
            {
              ...base.candidates[0]!,
              counterEvidenceIds: [],
              counterEvidenceTreatment: "NOT_APPLICABLE",
              counterEvidenceExplanation: null,
              missingEvidence: [],
              gate: null,
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("Evidence gate not evaluated.")).toBeVisible();
    expect(screen.getAllByText("None").length).toBeGreaterThan(0);
    rerender(
      <DiagnosisResults
        result={{
          ...base,
          candidates: [
            {
              ...base.candidates[0]!,
              gate: {
                ...base.candidates[0]!.gate!,
                outcome: "PASS",
                reasons: [],
                evaluatedEvidenceIds: [],
              },
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("No refusal reasons.")).toBeVisible();
    expect(screen.getByText("Evaluated evidence: None")).toBeVisible();
    rerender(
      <DiagnosisResults
        result={{
          ...base,
          candidates: [
            {
              ...base.candidates[0]!,
              gate: {
                ...base.candidates[0]!.gate!,
                reasons: [
                  {
                    code: "MISSING_EVIDENCE_DECLARED",
                    detail: "More evidence is required.",
                    evidenceIds: [],
                  },
                ],
              },
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(/More evidence is required/)).toBeVisible();
  });
});
