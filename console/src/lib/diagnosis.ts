import { consoleConfig } from "./config";

export const diagnosisDispositions = [
  "CANDIDATES",
  "NEEDS_MORE_EVIDENCE",
  "REFUSED",
  "HUMAN_HANDOFF",
] as const;
export const gateOutcomes = ["PASS", "FAIL"] as const;
export const counterEvidenceTreatments = [
  "NOT_APPLICABLE",
  "RESOLVED",
  "UNRESOLVED",
] as const;

export interface EvidenceGateReason {
  code: string;
  detail: string;
  evidenceIds: string[];
}

export interface EvidenceGateDecision {
  outcome: (typeof gateOutcomes)[number];
  reasons: EvidenceGateReason[];
  evaluatedEvidenceIds: string[];
  rulesVersion: string;
  inputFingerprint: string;
  decisionFingerprint: string;
  evaluatedAt: string;
  modelConfidenceBasisPoints: number | null;
  schemaVersion: string;
}

export interface RootCauseCandidate {
  candidateId: string;
  rank: number;
  statement: string;
  supportingEvidenceIds: string[];
  counterEvidenceIds: string[];
  counterEvidenceTreatment: (typeof counterEvidenceTreatments)[number];
  counterEvidenceExplanation: string | null;
  missingEvidence: string[];
  uncertainty: string;
  confidenceBasisPoints: number;
  gate: EvidenceGateDecision | null;
}

export interface DiagnosisResult {
  workflowRunId: string;
  modelCallId: string;
  reportFingerprint: string;
  producedAt: string;
  disposition: (typeof diagnosisDispositions)[number];
  candidates: RootCauseCandidate[];
  missingEvidence: string[];
  explanation: string;
  schemaVersion: string;
}

function invalid(): never {
  throw new Error("invalid diagnosis result response");
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return invalid();
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) return invalid();
  return value;
}

function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}

function integer(value: unknown, maximum = Number.MAX_SAFE_INTEGER): number {
  if (
    !Number.isInteger(value) ||
    (value as number) < 0 ||
    (value as number) > maximum
  ) {
    return invalid();
  }
  return value as number;
}

function texts(value: unknown, allowEmpty = true): string[] {
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0))
    return invalid();
  const result = value.map(text);
  if (new Set(result).size !== result.length) return invalid();
  return result;
}

function timestamp(value: unknown): string {
  const result = text(value);
  if (!Number.isFinite(Date.parse(result))) return invalid();
  return result;
}

function parseReason(value: unknown): EvidenceGateReason {
  const item = record(value);
  return {
    code: text(item.code),
    detail: text(item.detail),
    evidenceIds: texts(item.evidence_ids),
  };
}

function parseGate(value: unknown): EvidenceGateDecision {
  const item = record(value);
  const outcome = text(item.outcome);
  if (!gateOutcomes.includes(outcome as EvidenceGateDecision["outcome"]))
    return invalid();
  if (!Array.isArray(item.reasons)) return invalid();
  if ((outcome === "PASS") !== (item.reasons.length === 0)) return invalid();
  const confidence = item.model_confidence_basis_points;
  return {
    outcome: outcome as EvidenceGateDecision["outcome"],
    reasons: item.reasons.map(parseReason),
    evaluatedEvidenceIds: texts(item.evaluated_evidence_ids),
    rulesVersion: text(item.rules_version),
    inputFingerprint: text(item.input_fingerprint),
    decisionFingerprint: text(item.decision_fingerprint),
    evaluatedAt: timestamp(item.evaluated_at),
    modelConfidenceBasisPoints:
      confidence === null ? null : integer(confidence, 10_000),
    schemaVersion: text(item.schema_version),
  };
}

function parseCandidate(
  value: unknown,
  expectedRank: number,
): RootCauseCandidate {
  const item = record(value);
  const treatment = text(item.counter_evidence_treatment);
  if (
    !counterEvidenceTreatments.includes(
      treatment as RootCauseCandidate["counterEvidenceTreatment"],
    ) ||
    integer(item.rank) !== expectedRank
  ) {
    return invalid();
  }
  return {
    candidateId: text(item.candidate_id),
    rank: expectedRank,
    statement: text(item.statement),
    supportingEvidenceIds: texts(item.supporting_evidence_ids, false),
    counterEvidenceIds: texts(item.counter_evidence_ids),
    counterEvidenceTreatment:
      treatment as RootCauseCandidate["counterEvidenceTreatment"],
    counterEvidenceExplanation: nullableText(item.counter_evidence_explanation),
    missingEvidence: texts(item.missing_evidence),
    uncertainty: text(item.uncertainty),
    confidenceBasisPoints: integer(item.confidence_basis_points, 10_000),
    gate: item.gate === null ? null : parseGate(item.gate),
  };
}

function parseResult(value: unknown): DiagnosisResult {
  const item = record(value);
  const disposition = text(item.disposition);
  if (
    !diagnosisDispositions.includes(
      disposition as DiagnosisResult["disposition"],
    ) ||
    !Array.isArray(item.candidates)
  ) {
    return invalid();
  }
  const candidates = item.candidates.map((candidate, index) =>
    parseCandidate(candidate, index + 1),
  );
  if ((disposition === "CANDIDATES") !== candidates.length > 0)
    return invalid();
  return {
    workflowRunId: text(item.workflow_run_id),
    modelCallId: text(item.model_call_id),
    reportFingerprint: text(item.report_fingerprint),
    producedAt: timestamp(item.produced_at),
    disposition: disposition as DiagnosisResult["disposition"],
    candidates,
    missingEvidence: texts(item.missing_evidence),
    explanation: text(item.explanation),
    schemaVersion: text(item.schema_version),
  };
}

export async function loadDiagnosis(
  incidentId: string,
  signal?: AbortSignal,
): Promise<DiagnosisResult | null> {
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents/${encodeURIComponent(incidentId)}/diagnosis`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  if (!response.ok)
    throw new Error(`Diagnosis request failed (${response.status})`);
  const envelope = record(await response.json());
  return envelope.result === null ? null : parseResult(envelope.result);
}
