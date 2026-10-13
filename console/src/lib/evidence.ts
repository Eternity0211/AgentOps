import { consoleConfig } from "./config";

export const evidenceSourceTypes = [
  "METRIC",
  "LOG",
  "TRACE",
  "DEPLOYMENT",
  "TOPOLOGY",
] as const;

export const evidenceTrustClassifications = [
  "DIRECT_OBSERVATION",
  "DERIVED_OBSERVATION",
  "HISTORICAL_REFERENCE",
  "UNTRUSTED_INPUT",
] as const;

export const promptInjectionStatuses = [
  "NONE",
  "SUSPECTED",
  "QUARANTINED",
] as const;

export const artifactRedactionStatuses = ["NOT_REQUIRED", "REDACTED"] as const;

export interface EvidenceRecord {
  id: string;
  incidentId: string;
  sourceType: (typeof evidenceSourceTypes)[number];
  sourceInstance: string;
  toolName: string;
  toolVersion: string;
  toolSchemaVersion: string;
  normalizedQuery: Readonly<Record<string, string>>;
  observedFrom: string;
  observedTo: string;
  collectedAt: string;
  artifactId: string;
  contentHash: string;
  parserVersion: string;
  normalizerVersion: string;
  qualityScoreBasisPoints: number;
  qualityReasons: string[];
  toolCallId: string;
  workflowRunId: string;
  redactionTransformId: string | null;
  parentEvidenceIds: string[];
  trust: (typeof evidenceTrustClassifications)[number];
  promptInjectionStatus: (typeof promptInjectionStatuses)[number];
  expiresAt: string;
  expired: boolean;
  schemaVersion: string;
}

export interface EvidencePage {
  items: EvidenceRecord[];
  nextCursor: string | null;
}

export interface ArtifactPreview {
  artifactId: string;
  contentHash: string;
  contentSchemaVersion: string;
  redactionStatus: (typeof artifactRedactionStatuses)[number];
  mediaType: string;
  byteLength: number;
  content: string | null;
  previewReason: "unsupported_media_type" | "too_large" | null;
}

export class ArtifactLoadError extends Error {
  constructor(readonly status: number | null) {
    super(
      status === null
        ? "Artifact response failed integrity validation"
        : `Artifact request failed (${status})`,
    );
    this.name = "ArtifactLoadError";
  }
}

const MAX_PREVIEW_BYTES = 256 * 1024;
const SHA256 = /^[a-f0-9]{64}$/;
const MEDIA_TYPE = /^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/;

function invalidEvidence(): never {
  throw new Error("invalid evidence response");
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return invalidEvidence();
  }
  return value as Record<string, unknown>;
}

function string(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) return invalidEvidence();
  return value;
}

function nullableString(value: unknown): string | null {
  return value === null ? null : string(value);
}

function instant(value: unknown): string {
  const result = string(value);
  if (!Number.isFinite(Date.parse(result))) return invalidEvidence();
  return result;
}

function strings(value: unknown, options: { allowEmpty: boolean }): string[] {
  const { allowEmpty } = options;
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0)) {
    return invalidEvidence();
  }
  const result = value.map(string);
  if (new Set(result).size !== result.length) return invalidEvidence();
  return result;
}

function parseQuery(value: unknown): Readonly<Record<string, string>> {
  const source = record(value);
  const entries = Object.entries(source);
  if (entries.length === 0 || entries.length > 32) return invalidEvidence();
  const query: Record<string, string> = {};
  for (const [key, item] of entries) query[string(key)] = string(item);
  return query;
}

function parseEvidence(
  value: unknown,
  expectedIncidentId: string,
): EvidenceRecord {
  const item = record(value);
  const incidentId = string(item.incident_id);
  const sourceType = string(item.source_type);
  const trust = string(item.trust);
  const promptInjectionStatus = string(item.prompt_injection_status);
  const contentHash = string(item.content_hash);
  const observedFrom = instant(item.observed_from);
  const observedTo = instant(item.observed_to);
  const collectedAt = instant(item.collected_at);
  const expiresAt = instant(item.expires_at);
  const qualityScore = item.quality_score_basis_points;
  if (
    incidentId !== expectedIncidentId ||
    !evidenceSourceTypes.includes(sourceType as EvidenceRecord["sourceType"]) ||
    !evidenceTrustClassifications.includes(trust as EvidenceRecord["trust"]) ||
    !promptInjectionStatuses.includes(
      promptInjectionStatus as EvidenceRecord["promptInjectionStatus"],
    ) ||
    !SHA256.test(contentHash) ||
    !Number.isInteger(qualityScore) ||
    (qualityScore as number) < 0 ||
    (qualityScore as number) > 10_000 ||
    typeof item.expired !== "boolean" ||
    Date.parse(observedFrom) > Date.parse(observedTo) ||
    Date.parse(observedTo) > Date.parse(collectedAt) ||
    Date.parse(collectedAt) >= Date.parse(expiresAt)
  ) {
    return invalidEvidence();
  }
  return {
    id: string(item.id),
    incidentId,
    sourceType: sourceType as EvidenceRecord["sourceType"],
    sourceInstance: string(item.source_instance),
    toolName: string(item.tool_name),
    toolVersion: string(item.tool_version),
    toolSchemaVersion: string(item.tool_schema_version),
    normalizedQuery: parseQuery(item.normalized_query),
    observedFrom,
    observedTo,
    collectedAt,
    artifactId: string(item.artifact_id),
    contentHash,
    parserVersion: string(item.parser_version),
    normalizerVersion: string(item.normalizer_version),
    qualityScoreBasisPoints: qualityScore as number,
    qualityReasons: strings(item.quality_reasons, { allowEmpty: false }),
    toolCallId: string(item.tool_call_id),
    workflowRunId: string(item.workflow_run_id),
    redactionTransformId: nullableString(item.redaction_transform_id),
    parentEvidenceIds: strings(item.parent_evidence_ids, { allowEmpty: true }),
    trust: trust as EvidenceRecord["trust"],
    promptInjectionStatus:
      promptInjectionStatus as EvidenceRecord["promptInjectionStatus"],
    expiresAt,
    expired: item.expired,
    schemaVersion: string(item.schema_version),
  };
}

export async function loadEvidence(
  incidentId: string,
  cursor?: string,
  signal?: AbortSignal,
): Promise<EvidencePage> {
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) query.set("cursor", cursor);
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents/${encodeURIComponent(incidentId)}/evidence?${query}`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  if (!response.ok) {
    throw new Error(`Evidence request failed (${response.status})`);
  }
  const page = record(await response.json());
  if (
    !Array.isArray(page.items) ||
    !(
      page.next_cursor === null ||
      (typeof page.next_cursor === "string" && page.next_cursor.length > 0)
    )
  ) {
    return invalidEvidence();
  }
  const items = page.items.map((item) => parseEvidence(item, incidentId));
  if (
    new Set(items.map((item) => item.id)).size !== items.length ||
    new Set(items.map((item) => item.artifactId)).size !== items.length
  ) {
    return invalidEvidence();
  }
  return { items, nextCursor: page.next_cursor };
}

function artifactHeader(response: Response, name: string): string {
  const value = response.headers.get(name);
  if (value === null || value.length === 0) throw new ArtifactLoadError(null);
  return value;
}

export async function loadArtifact(
  incidentId: string,
  evidence: Pick<EvidenceRecord, "id" | "artifactId" | "contentHash">,
  signal?: AbortSignal,
): Promise<ArtifactPreview> {
  const response = await fetch(
    `${consoleConfig.apiBaseUrl}/incidents/${encodeURIComponent(incidentId)}/evidence/${encodeURIComponent(evidence.id)}/artifact`,
    {
      cache: "no-store",
      credentials: "include",
      headers: { Accept: "application/json, text/plain;q=0.9, */*;q=0.1" },
      signal,
    },
  );
  if (!response.ok) throw new ArtifactLoadError(response.status);

  const artifactId = artifactHeader(response, "X-Artifact-ID");
  const contentHash = artifactHeader(response, "X-Content-SHA256");
  const contentSchemaVersion = artifactHeader(
    response,
    "X-Content-Schema-Version",
  );
  const redactionStatus = artifactHeader(response, "X-Redaction-Status");
  const rawMediaType = artifactHeader(response, "Content-Type")
    .split(";", 1)[0]!
    .trim()
    .toLowerCase();
  const cacheControl = artifactHeader(response, "Cache-Control")
    .toLowerCase()
    .split(",")
    .map((part) => part.trim());
  const etag = artifactHeader(response, "ETag");
  if (
    artifactId !== evidence.artifactId ||
    contentHash !== evidence.contentHash ||
    !SHA256.test(contentHash) ||
    !MEDIA_TYPE.test(rawMediaType) ||
    !artifactRedactionStatuses.includes(
      redactionStatus as ArtifactPreview["redactionStatus"],
    ) ||
    !cacheControl.includes("private") ||
    !cacheControl.includes("no-store") ||
    etag !== `"sha256:${contentHash}"`
  ) {
    throw new ArtifactLoadError(null);
  }

  const bytes = await response.arrayBuffer();
  const textual =
    rawMediaType.startsWith("text/") ||
    rawMediaType === "application/json" ||
    rawMediaType.endsWith("+json");
  const tooLarge = bytes.byteLength > MAX_PREVIEW_BYTES;
  return {
    artifactId,
    contentHash,
    contentSchemaVersion,
    redactionStatus: redactionStatus as ArtifactPreview["redactionStatus"],
    mediaType: rawMediaType,
    byteLength: bytes.byteLength,
    content:
      textual && !tooLarge
        ? new TextDecoder("utf-8", { fatal: false }).decode(bytes)
        : null,
    previewReason: tooLarge
      ? "too_large"
      : textual
        ? null
        : "unsupported_media_type",
  };
}
