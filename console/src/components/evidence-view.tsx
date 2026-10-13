"use client";

import { useEffect, useRef, useState } from "react";

import {
  ArtifactLoadError,
  loadArtifact,
  loadEvidence,
  type ArtifactPreview,
  type EvidencePage,
  type EvidenceRecord,
} from "@/lib/evidence";

type ArtifactState =
  | { status: "idle" }
  | { status: "loading"; evidenceId: string }
  | { status: "ready"; evidenceId: string; preview: ArtifactPreview }
  | { status: "error"; evidenceId: string; message: string };

function displayState(value: string) {
  return value.replaceAll("_", " ");
}

function displayTime(value: string) {
  return new Date(value).toLocaleString();
}

function artifactFailure(error: unknown) {
  if (!(error instanceof ArtifactLoadError)) {
    return "Artifact could not be loaded.";
  }
  if (error.status === 410) {
    return "Artifact has expired and is no longer available.";
  }
  if (error.status === 409 || error.status === null) {
    return "Artifact integrity verification failed. No content was displayed.";
  }
  if (error.status === 503) {
    return "Artifact storage is temporarily unavailable.";
  }
  return "Artifact could not be loaded.";
}

function ArtifactResult({ preview }: Readonly<{ preview: ArtifactPreview }>) {
  return (
    <div className="artifact-result">
      <dl className="artifact-metadata">
        <div>
          <dt>Media type</dt>
          <dd>{preview.mediaType}</dd>
        </div>
        <div>
          <dt>Content schema</dt>
          <dd>{preview.contentSchemaVersion}</dd>
        </div>
        <div>
          <dt>Redaction</dt>
          <dd>{displayState(preview.redactionStatus)}</dd>
        </div>
        <div>
          <dt>Verified bytes</dt>
          <dd>{preview.byteLength.toLocaleString()}</dd>
        </div>
      </dl>
      {preview.content !== null ? (
        <pre aria-label="Verified artifact content">{preview.content}</pre>
      ) : preview.previewReason === "too_large" ? (
        <p role="status">
          Content was verified but exceeds the 256 KiB safe preview limit.
        </p>
      ) : (
        <p role="status">
          Content was verified. This media type is not rendered in the console.
        </p>
      )}
    </div>
  );
}

function EvidenceCard({
  artifactState,
  evidence,
  onArtifact,
}: Readonly<{
  artifactState: ArtifactState;
  evidence: EvidenceRecord;
  onArtifact: (evidence: EvidenceRecord) => void;
}>) {
  const artifactForItem =
    artifactState.status !== "idle" && artifactState.evidenceId === evidence.id
      ? artifactState
      : null;
  return (
    <li>
      <article className="evidence-card">
        <div className="evidence-heading">
          <div>
            <p className="eyebrow">{evidence.sourceType} EVIDENCE</p>
            <h3>{evidence.id}</h3>
          </div>
          <div className="evidence-flags">
            <span>{displayState(evidence.trust)}</span>
            <span
              className={
                evidence.promptInjectionStatus === "NONE"
                  ? undefined
                  : "flag-warning"
              }
            >
              Injection: {displayState(evidence.promptInjectionStatus)}
            </span>
            <span className={evidence.expired ? "flag-danger" : undefined}>
              {evidence.expired ? "Expired" : "Current"}
            </span>
          </div>
        </div>

        <dl className="evidence-metadata">
          <div>
            <dt>Source</dt>
            <dd>{evidence.sourceInstance}</dd>
          </div>
          <div>
            <dt>Collected by</dt>
            <dd>
              {evidence.toolName} v{evidence.toolVersion}
            </dd>
          </div>
          <div>
            <dt>Tool schema</dt>
            <dd>{evidence.toolSchemaVersion}</dd>
          </div>
          <div>
            <dt>Observed from</dt>
            <dd>{displayTime(evidence.observedFrom)}</dd>
          </div>
          <div>
            <dt>Observed to</dt>
            <dd>{displayTime(evidence.observedTo)}</dd>
          </div>
          <div>
            <dt>Collected</dt>
            <dd>{displayTime(evidence.collectedAt)}</dd>
          </div>
          <div>
            <dt>Quality</dt>
            <dd>
              {(evidence.qualityScoreBasisPoints / 100).toFixed(2)}% ·{" "}
              {evidence.qualityReasons.join(", ")}
            </dd>
          </div>
          <div>
            <dt>Expires</dt>
            <dd>{displayTime(evidence.expiresAt)}</dd>
          </div>
          <div>
            <dt>Evidence schema</dt>
            <dd>{evidence.schemaVersion}</dd>
          </div>
          <div>
            <dt>Parser / normalizer</dt>
            <dd>
              {evidence.parserVersion} / {evidence.normalizerVersion}
            </dd>
          </div>
          <div>
            <dt>Workflow run</dt>
            <dd>{evidence.workflowRunId}</dd>
          </div>
          <div>
            <dt>Tool call</dt>
            <dd>{evidence.toolCallId}</dd>
          </div>
          <div>
            <dt>Redaction transform</dt>
            <dd>{evidence.redactionTransformId ?? "None"}</dd>
          </div>
          <div>
            <dt>Parent evidence</dt>
            <dd>
              {evidence.parentEvidenceIds.length === 0
                ? "None"
                : evidence.parentEvidenceIds.join(", ")}
            </dd>
          </div>
        </dl>

        <div className="evidence-query">
          <h4>Normalized query</h4>
          <dl>
            {Object.entries(evidence.normalizedQuery).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="artifact-binding">
          <p>
            Artifact <strong>{evidence.artifactId}</strong>
          </p>
          <p className="content-hash">SHA-256 {evidence.contentHash}</p>
          <button
            type="button"
            disabled={evidence.expired || artifactForItem?.status === "loading"}
            onClick={() => onArtifact(evidence)}
          >
            {evidence.expired
              ? "Artifact expired"
              : artifactForItem?.status === "loading"
                ? "Verifying artifact…"
                : artifactForItem?.status === "ready"
                  ? "Reload artifact"
                  : artifactForItem?.status === "error"
                    ? "Retry artifact"
                    : "View verified artifact"}
          </button>
        </div>
        {artifactForItem?.status === "ready" ? (
          <ArtifactResult preview={artifactForItem.preview} />
        ) : null}
        {artifactForItem?.status === "error" ? (
          <p className="artifact-error" role="alert">
            {artifactForItem.message}
          </p>
        ) : null}
      </article>
    </li>
  );
}

export function EvidenceView({
  incidentId,
  initialPage,
}: Readonly<{ incidentId: string; initialPage: EvidencePage }>) {
  const [page, setPage] = useState(initialPage);
  const [pageBusy, setPageBusy] = useState(false);
  const [pageError, setPageError] = useState(false);
  const [artifactState, setArtifactState] = useState<ArtifactState>({
    status: "idle",
  });
  const pageController = useRef<AbortController | null>(null);
  const artifactController = useRef<AbortController | null>(null);

  useEffect(() => {
    pageController.current?.abort();
    artifactController.current?.abort();
    setPage(initialPage);
    setPageBusy(false);
    setPageError(false);
    setArtifactState({ status: "idle" });
    return () => {
      pageController.current?.abort();
      artifactController.current?.abort();
    };
  }, [incidentId, initialPage]);

  async function loadMore(cursor: string) {
    const controller = new AbortController();
    pageController.current?.abort();
    pageController.current = controller;
    setPageBusy(true);
    setPageError(false);
    try {
      const next = await loadEvidence(incidentId, cursor, controller.signal);
      if (!controller.signal.aborted) {
        const evidenceIds = new Set(page.items.map((item) => item.id));
        const artifactIds = new Set(page.items.map((item) => item.artifactId));
        if (
          next.items.some(
            (item) =>
              evidenceIds.has(item.id) || artifactIds.has(item.artifactId),
          )
        ) {
          setPageError(true);
        } else {
          setPage({
            items: [...page.items, ...next.items],
            nextCursor: next.nextCursor,
          });
        }
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setPageError(true);
      }
    } finally {
      if (!controller.signal.aborted) setPageBusy(false);
    }
  }

  async function showArtifact(evidence: EvidenceRecord) {
    const controller = new AbortController();
    artifactController.current?.abort();
    artifactController.current = controller;
    setArtifactState({ status: "loading", evidenceId: evidence.id });
    try {
      const preview = await loadArtifact(
        incidentId,
        evidence,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setArtifactState({ status: "ready", evidenceId: evidence.id, preview });
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setArtifactState({
          status: "error",
          evidenceId: evidence.id,
          message: artifactFailure(error),
        });
      }
    }
  }

  return (
    <section aria-labelledby="evidence-artifacts" className="evidence-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">IMMUTABLE PROVENANCE</p>
          <h2 id="evidence-artifacts">Evidence and artifacts</h2>
        </div>
        <span>{page.items.length} evidence records loaded</span>
      </div>
      {page.items.length === 0 ? (
        <div className="panel">
          <p>No evidence has been recorded for this incident.</p>
        </div>
      ) : (
        <ol className="evidence-list">
          {page.items.map((evidence) => (
            <EvidenceCard
              artifactState={artifactState}
              evidence={evidence}
              key={evidence.id}
              onArtifact={(item) => void showArtifact(item)}
            />
          ))}
        </ol>
      )}
      {pageError ? (
        <p role="alert">
          Additional evidence could not be verified. Loaded evidence was kept.
        </p>
      ) : null}
      {page.nextCursor !== null ? (
        <button
          type="button"
          disabled={pageBusy}
          onClick={() => void loadMore(page.nextCursor as string)}
        >
          {pageBusy
            ? "Loading more evidence…"
            : pageError
              ? "Retry older evidence"
              : "Load more evidence"}
        </button>
      ) : null}
    </section>
  );
}
