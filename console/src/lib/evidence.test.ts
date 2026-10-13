import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ArtifactLoadError,
  loadArtifact,
  loadEvidence,
  type EvidenceRecord,
} from "./evidence";

const HASH = "a".repeat(64);

function evidence(overrides: Record<string, unknown> = {}) {
  return {
    id: "evidence-1",
    incident_id: "incident-1",
    source_type: "LOG",
    source_instance: "loki-primary",
    tool_name: "query_logs",
    tool_version: "1.0.0",
    tool_schema_version: "1.0.0",
    normalized_query: { service: "orders", level: "error" },
    observed_from: "2026-10-11T10:00:00Z",
    observed_to: "2026-10-11T10:01:00Z",
    collected_at: "2026-10-11T10:02:00Z",
    artifact_id: "artifact-1",
    content_hash: HASH,
    parser_version: "1.0.0",
    normalizer_version: "1.0.0",
    quality_score_basis_points: 9000,
    quality_reasons: ["complete-window"],
    tool_call_id: "tool-call-1",
    workflow_run_id: "workflow-1",
    redaction_transform_id: "redaction-1",
    parent_evidence_ids: ["evidence-parent"],
    trust: "DIRECT_OBSERVATION",
    prompt_injection_status: "NONE",
    expires_at: "2026-10-18T10:02:00Z",
    expired: false,
    schema_version: "1.0.0",
    ...overrides,
  };
}

function evidenceRecord(): EvidenceRecord {
  return {
    id: "evidence-1",
    incidentId: "incident-1",
    sourceType: "LOG",
    sourceInstance: "loki-primary",
    toolName: "query_logs",
    toolVersion: "1.0.0",
    toolSchemaVersion: "1.0.0",
    normalizedQuery: { service: "orders" },
    observedFrom: "2026-10-11T10:00:00Z",
    observedTo: "2026-10-11T10:01:00Z",
    collectedAt: "2026-10-11T10:02:00Z",
    artifactId: "artifact-1",
    contentHash: HASH,
    parserVersion: "1.0.0",
    normalizerVersion: "1.0.0",
    qualityScoreBasisPoints: 9000,
    qualityReasons: ["complete-window"],
    toolCallId: "tool-call-1",
    workflowRunId: "workflow-1",
    redactionTransformId: null,
    parentEvidenceIds: [],
    trust: "DIRECT_OBSERVATION",
    promptInjectionStatus: "NONE",
    expiresAt: "2026-10-18T10:02:00Z",
    expired: false,
    schemaVersion: "1.0.0",
  };
}

function artifactResponse(
  body: BodyInit = '{"status":"verified"}',
  headerOverrides: Record<string, string> = {},
) {
  return new Response(body, {
    status: 200,
    headers: {
      "Cache-Control": "private, no-store",
      "Content-Type": "application/json; charset=utf-8",
      ETag: `"sha256:${HASH}"`,
      "X-Artifact-ID": "artifact-1",
      "X-Content-SHA256": HASH,
      "X-Content-Schema-Version": "1.0.0",
      "X-Redaction-Status": "REDACTED",
      ...headerOverrides,
    },
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("loadEvidence", () => {
  it("loads and strictly maps an incident-owned evidence page", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [evidence({ incident_id: "incident / one" })],
          next_cursor: "opaque+next",
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const page = await loadEvidence("incident / one", "cursor+current");
    expect(page).toEqual({
      items: [
        expect.objectContaining({
          id: "evidence-1",
          incidentId: "incident / one",
          sourceType: "LOG",
          normalizedQuery: { service: "orders", level: "error" },
          qualityScoreBasisPoints: 9000,
          redactionTransformId: "redaction-1",
          parentEvidenceIds: ["evidence-parent"],
        }),
      ],
      nextCursor: "opaque+next",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/incidents/incident%20%2F%20one/evidence?limit=20&cursor=cursor%2Bcurrent",
      expect.objectContaining({
        cache: "no-store",
        credentials: "include",
        headers: { Accept: "application/json" },
      }),
    );
  });

  it("loads an empty terminal page without a cursor", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ items: [], next_cursor: null })),
        ),
    );
    await expect(loadEvidence("incident-1")).resolves.toEqual({
      items: [],
      nextCursor: null,
    });
  });

  it("accepts evidence without a redaction transform or parent lineage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            items: [
              evidence({
                redaction_transform_id: null,
                parent_evidence_ids: [],
              }),
            ],
            next_cursor: null,
          }),
        ),
      ),
    );
    const page = await loadEvidence("incident-1");
    expect(page.items[0]).toEqual(
      expect.objectContaining({
        redactionTransformId: null,
        parentEvidenceIds: [],
      }),
    );
  });

  it("rejects unsuccessful API responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 403 })),
    );
    await expect(loadEvidence("incident-1")).rejects.toThrow(
      "Evidence request failed (403)",
    );
  });

  it.each([
    null,
    [],
    {},
    { items: null, next_cursor: null },
    { items: [], next_cursor: 2 },
    { items: [], next_cursor: "" },
    { items: [null], next_cursor: null },
    {
      items: [evidence({ incident_id: "incident-foreign" })],
      next_cursor: null,
    },
    { items: [evidence({ source_type: "UNKNOWN" })], next_cursor: null },
    { items: [evidence({ trust: "UNKNOWN" })], next_cursor: null },
    {
      items: [evidence({ prompt_injection_status: "UNKNOWN" })],
      next_cursor: null,
    },
    { items: [evidence({ content_hash: "bad" })], next_cursor: null },
    {
      items: [evidence({ quality_score_basis_points: 2.5 })],
      next_cursor: null,
    },
    {
      items: [evidence({ quality_score_basis_points: -1 })],
      next_cursor: null,
    },
    {
      items: [evidence({ quality_score_basis_points: 10_001 })],
      next_cursor: null,
    },
    { items: [evidence({ expired: "false" })], next_cursor: null },
    {
      items: [
        evidence({
          observed_from: "2026-10-11T10:02:00Z",
          observed_to: "2026-10-11T10:01:00Z",
        }),
      ],
      next_cursor: null,
    },
    {
      items: [
        evidence({
          observed_to: "2026-10-11T10:03:00Z",
          collected_at: "2026-10-11T10:02:00Z",
        }),
      ],
      next_cursor: null,
    },
    {
      items: [
        evidence({
          collected_at: "2026-10-18T10:02:00Z",
          expires_at: "2026-10-18T10:02:00Z",
        }),
      ],
      next_cursor: null,
    },
    { items: [evidence({ id: "" })], next_cursor: null },
    { items: [evidence({ observed_from: "not-a-date" })], next_cursor: null },
    { items: [evidence({ normalized_query: [] })], next_cursor: null },
    { items: [evidence({ normalized_query: {} })], next_cursor: null },
    {
      items: [
        evidence({
          normalized_query: Object.fromEntries(
            Array.from({ length: 33 }, (_, index) => [`key${index}`, "value"]),
          ),
        }),
      ],
      next_cursor: null,
    },
    {
      items: [evidence({ normalized_query: { service: 1 } })],
      next_cursor: null,
    },
    { items: [evidence({ quality_reasons: [] })], next_cursor: null },
    { items: [evidence({ quality_reasons: null })], next_cursor: null },
    {
      items: [evidence({ quality_reasons: ["same", "same"] })],
      next_cursor: null,
    },
    {
      items: [evidence({ redaction_transform_id: 1 })],
      next_cursor: null,
    },
    { items: [evidence({ parent_evidence_ids: null })], next_cursor: null },
    {
      items: [evidence({ parent_evidence_ids: ["same", "same"] })],
      next_cursor: null,
    },
    {
      items: [evidence(), evidence()],
      next_cursor: null,
    },
    {
      items: [evidence(), evidence({ id: "evidence-2" })],
      next_cursor: null,
    },
  ])("rejects malformed or unowned evidence payload %#", async (body) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(body))),
    );
    await expect(loadEvidence("incident-1")).rejects.toThrow(
      "invalid evidence response",
    );
  });
});

describe("loadArtifact", () => {
  it.each([
    ["text/plain", "plain text"],
    ["application/json", '{"safe":true}'],
    ["application/problem+json", '{"safe":true}'],
  ])("returns a verified safe preview for %s", async (mediaType, body) => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(artifactResponse(body, { "Content-Type": mediaType }));
    vi.stubGlobal("fetch", fetchMock);
    const preview = await loadArtifact("incident / one", evidenceRecord());
    expect(preview).toEqual({
      artifactId: "artifact-1",
      contentHash: HASH,
      contentSchemaVersion: "1.0.0",
      redactionStatus: "REDACTED",
      mediaType,
      byteLength: new TextEncoder().encode(body).byteLength,
      content: body,
      previewReason: null,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/incidents/incident%20%2F%20one/evidence/evidence-1/artifact",
      expect.objectContaining({
        cache: "no-store",
        credentials: "include",
      }),
    );
  });

  it("verifies but does not render unsupported binary content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        artifactResponse(new Uint8Array([1, 2]), {
          "Content-Type": "application/octet-stream",
          "X-Redaction-Status": "NOT_REQUIRED",
        }),
      ),
    );
    await expect(loadArtifact("incident-1", evidenceRecord())).resolves.toEqual(
      expect.objectContaining({
        byteLength: 2,
        content: null,
        previewReason: "unsupported_media_type",
        redactionStatus: "NOT_REQUIRED",
      }),
    );
  });

  it("verifies but does not render oversized content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(artifactResponse("x".repeat(256 * 1024 + 1))),
    );
    await expect(loadArtifact("incident-1", evidenceRecord())).resolves.toEqual(
      expect.objectContaining({ content: null, previewReason: "too_large" }),
    );
  });

  it("preserves an unsuccessful response status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 410 })),
    );
    await expect(loadArtifact("incident-1", evidenceRecord())).rejects.toEqual(
      expect.objectContaining({
        name: "ArtifactLoadError",
        status: 410,
        message: "Artifact request failed (410)",
      }),
    );
  });

  it("rejects a missing mandatory response header", async () => {
    const response = artifactResponse();
    response.headers.delete("X-Artifact-ID");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(loadArtifact("incident-1", evidenceRecord())).rejects.toEqual(
      new ArtifactLoadError(null),
    );
  });

  it.each([
    { "X-Artifact-ID": "artifact-other" },
    { "X-Content-SHA256": "b".repeat(64) },
    { "X-Content-SHA256": "bad" },
    { "Content-Type": "invalid" },
    { "X-Redaction-Status": "UNKNOWN" },
    { "Cache-Control": "no-store" },
    { "Cache-Control": "private" },
    { ETag: `"sha256:${"b".repeat(64)}"` },
  ] as Record<string, string>[])(
    "rejects an unverified artifact binding %#",
    async (headers) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(artifactResponse("safe", headers)),
      );
      await expect(
        loadArtifact("incident-1", evidenceRecord()),
      ).rejects.toEqual(expect.objectContaining({ status: null }));
    },
  );
});
