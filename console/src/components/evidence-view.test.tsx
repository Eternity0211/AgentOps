import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArtifactLoadError, type EvidenceRecord } from "@/lib/evidence";

import { EvidenceView } from "./evidence-view";

const mocks = vi.hoisted(() => ({
  loadArtifact: vi.fn(),
  loadEvidence: vi.fn(),
}));

vi.mock("@/lib/evidence", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/evidence")>()),
  loadArtifact: mocks.loadArtifact,
  loadEvidence: mocks.loadEvidence,
}));

const HASH = "a".repeat(64);

function evidence(overrides: Partial<EvidenceRecord> = {}): EvidenceRecord {
  return {
    id: "evidence-1",
    incidentId: "incident-1",
    sourceType: "LOG",
    sourceInstance: "loki-primary",
    toolName: "query_logs",
    toolVersion: "1.0.0",
    toolSchemaVersion: "1.1.0",
    normalizedQuery: { service: "orders", level: "error" },
    observedFrom: "2026-10-11T10:00:00Z",
    observedTo: "2026-10-11T10:01:00Z",
    collectedAt: "2026-10-11T10:02:00Z",
    artifactId: "artifact-1",
    contentHash: HASH,
    parserVersion: "2.0.0",
    normalizerVersion: "3.0.0",
    qualityScoreBasisPoints: 9125,
    qualityReasons: ["complete-window", "direct-source"],
    toolCallId: "tool-call-1",
    workflowRunId: "workflow-1",
    redactionTransformId: "redaction-1",
    parentEvidenceIds: ["evidence-parent"],
    trust: "DIRECT_OBSERVATION",
    promptInjectionStatus: "NONE",
    expiresAt: "2026-10-18T10:02:00Z",
    expired: false,
    schemaVersion: "1.0.0",
    ...overrides,
  };
}

const preview = {
  artifactId: "artifact-1",
  contentHash: HASH,
  contentSchemaVersion: "1.0.0",
  redactionStatus: "REDACTED" as const,
  mediaType: "application/json",
  byteLength: 17,
  content: '{"verified":true}',
  previewReason: null,
};

beforeEach(() => {
  mocks.loadArtifact.mockReset();
  mocks.loadEvidence.mockReset();
});

describe("EvidenceView", () => {
  it("renders a clear empty state", () => {
    render(
      <EvidenceView
        incidentId="incident-1"
        initialPage={{ items: [], nextCursor: null }}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Evidence and artifacts" }),
    ).toBeVisible();
    expect(
      screen.getByText("No evidence has been recorded for this incident."),
    ).toBeVisible();
    expect(screen.getByText("0 evidence records loaded")).toBeVisible();
  });

  it("shows complete provenance, blocks expired content, and previews verified text", async () => {
    const current = evidence();
    const expired = evidence({
      id: "evidence-expired",
      artifactId: "artifact-expired",
      expired: true,
      trust: "UNTRUSTED_INPUT",
      promptInjectionStatus: "QUARANTINED",
      redactionTransformId: null,
      parentEvidenceIds: [],
    });
    let resolveArtifact!: (value: typeof preview) => void;
    mocks.loadArtifact.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveArtifact = resolve;
        }),
    );
    render(
      <EvidenceView
        incidentId="incident-1"
        initialPage={{ items: [current, expired], nextCursor: null }}
      />,
    );

    expect(
      screen.getAllByText("91.25% · complete-window, direct-source"),
    ).toHaveLength(2);
    expect(screen.getAllByText("query_logs v1.0.0")).toHaveLength(2);
    expect(screen.getAllByText("2.0.0 / 3.0.0")).toHaveLength(2);
    expect(screen.getByText("evidence-parent")).toBeVisible();
    expect(screen.getByText("Injection: QUARANTINED")).toBeVisible();
    expect(screen.getAllByText("None")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "Artifact expired" }),
    ).toBeDisabled();

    fireEvent.click(
      screen.getByRole("button", { name: "View verified artifact" }),
    );
    expect(
      screen.getByRole("button", { name: "Verifying artifact…" }),
    ).toBeDisabled();
    expect(mocks.loadArtifact).toHaveBeenCalledWith(
      "incident-1",
      current,
      expect.any(AbortSignal),
    );
    await act(async () => resolveArtifact(preview));
    expect(
      await screen.findByLabelText("Verified artifact content"),
    ).toHaveTextContent('{"verified":true}');
    expect(screen.getByText("REDACTED")).toBeVisible();
    expect(screen.getByText("17")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Reload artifact" }),
    ).toBeVisible();
  });

  it("reports verified binary and oversized artifacts without rendering them", async () => {
    mocks.loadArtifact
      .mockResolvedValueOnce({
        ...preview,
        mediaType: "application/octet-stream",
        content: null,
        previewReason: "unsupported_media_type",
      })
      .mockResolvedValueOnce({
        ...preview,
        byteLength: 300_000,
        content: null,
        previewReason: "too_large",
      });
    render(
      <EvidenceView
        incidentId="incident-1"
        initialPage={{ items: [evidence()], nextCursor: null }}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "View verified artifact" }),
    );
    expect(
      await screen.findByText("This media type is not rendered", {
        exact: false,
      }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reload artifact" }));
    expect(
      await screen.findByText("exceeds the 256 KiB safe preview limit", {
        exact: false,
      }),
    ).toBeVisible();
  });

  it.each([
    [new ArtifactLoadError(410), "has expired"],
    [new ArtifactLoadError(409), "integrity verification failed"],
    [new ArtifactLoadError(null), "integrity verification failed"],
    [new ArtifactLoadError(503), "temporarily unavailable"],
    [new ArtifactLoadError(404), "could not be loaded"],
    [new Error("network"), "could not be loaded"],
  ])(
    "maps artifact failures without exposing content %#",
    async (error, message) => {
      mocks.loadArtifact.mockRejectedValue(error);
      render(
        <EvidenceView
          incidentId="incident-1"
          initialPage={{ items: [evidence()], nextCursor: null }}
        />,
      );
      fireEvent.click(
        screen.getByRole("button", { name: "View verified artifact" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(message);
      expect(
        screen.getByRole("button", { name: "Retry artifact" }),
      ).toBeVisible();
      expect(screen.queryByLabelText("Verified artifact content")).toBeNull();
    },
  );

  it("appends a verified cursor page", async () => {
    let resolveMore!: (value: {
      items: EvidenceRecord[];
      nextCursor: null;
    }) => void;
    mocks.loadEvidence.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveMore = resolve;
        }),
    );
    render(
      <EvidenceView
        incidentId="incident-1"
        initialPage={{ items: [evidence()], nextCursor: "opaque-next" }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Load more evidence" }));
    expect(
      screen.getByRole("button", { name: "Loading more evidence…" }),
    ).toBeDisabled();
    expect(mocks.loadEvidence).toHaveBeenCalledWith(
      "incident-1",
      "opaque-next",
      expect.any(AbortSignal),
    );
    await act(async () =>
      resolveMore({
        items: [evidence({ id: "evidence-2", artifactId: "artifact-2" })],
        nextCursor: null,
      }),
    );
    expect(await screen.findByText("2 evidence records loaded")).toBeVisible();
    expect(screen.queryByRole("button", { name: /evidence$/ })).toBeNull();
  });

  it.each([[evidence()], [evidence({ id: "evidence-2" })]])(
    "rejects overlapping cursor results without discarding records %#",
    async (item) => {
      mocks.loadEvidence.mockResolvedValue({ items: [item], nextCursor: null });
      render(
        <EvidenceView
          incidentId="incident-1"
          initialPage={{ items: [evidence()], nextCursor: "opaque-next" }}
        />,
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Load more evidence" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "could not be verified",
      );
      expect(screen.getByText("1 evidence records loaded")).toBeVisible();
      expect(
        screen.getByRole("button", { name: "Retry older evidence" }),
      ).toBeVisible();
    },
  );

  it("retries page failures while preserving loaded evidence", async () => {
    mocks.loadEvidence
      .mockRejectedValueOnce(new Error("offline"))
      .mockRejectedValueOnce(new DOMException("offline", "NetworkError"))
      .mockResolvedValueOnce({
        items: [evidence({ id: "evidence-2", artifactId: "artifact-2" })],
        nextCursor: null,
      });
    render(
      <EvidenceView
        incidentId="incident-1"
        initialPage={{ items: [evidence()], nextCursor: "next" }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Load more evidence" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry older evidence" }),
    );
    await waitFor(() => expect(mocks.loadEvidence).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("alert")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry older evidence" }),
    );
    expect(await screen.findByText("2 evidence records loaded")).toBeVisible();
  });

  it("aborts in-flight page and artifact reads when the incident changes", async () => {
    const pending = (...args: unknown[]) => {
      const signal = args.at(-1) as AbortSignal;
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () =>
          reject(new DOMException("cancelled", "AbortError")),
        );
      });
    };
    mocks.loadEvidence.mockImplementation(pending);
    mocks.loadArtifact.mockImplementation(pending);
    const firstPage = { items: [evidence()], nextCursor: "next" };
    const view = render(
      <EvidenceView incidentId="incident-1" initialPage={firstPage} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Load more evidence" }));
    fireEvent.click(
      screen.getByRole("button", { name: "View verified artifact" }),
    );
    view.rerender(
      <EvidenceView
        incidentId="incident-2"
        initialPage={{ items: [], nextCursor: null }}
      />,
    );
    expect(
      await screen.findByText(
        "No evidence has been recorded for this incident.",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ignores late page and artifact success after unmount", async () => {
    let resolveMore!: (value: { items: never[]; nextCursor: null }) => void;
    let resolveArtifact!: (value: typeof preview) => void;
    mocks.loadEvidence.mockImplementation(
      () => new Promise((resolve) => (resolveMore = resolve)),
    );
    mocks.loadArtifact.mockImplementation(
      () => new Promise((resolve) => (resolveArtifact = resolve)),
    );
    const view = render(
      <EvidenceView
        incidentId="incident-1"
        initialPage={{ items: [evidence()], nextCursor: "next" }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Load more evidence" }));
    fireEvent.click(
      screen.getByRole("button", { name: "View verified artifact" }),
    );
    view.unmount();
    await act(async () => {
      resolveMore({ items: [], nextCursor: null });
      resolveArtifact(preview);
    });
    expect(mocks.loadEvidence).toHaveBeenCalledOnce();
    expect(mocks.loadArtifact).toHaveBeenCalledOnce();
  });
});
