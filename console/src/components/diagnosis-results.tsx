import type {
  DiagnosisResult,
  EvidenceGateDecision,
  RootCauseCandidate,
} from "@/lib/diagnosis";

function displayState(value: string) {
  return value.replaceAll("_", " ");
}

function evidenceLinks(ids: string[]) {
  if (ids.length === 0) return <span>None</span>;
  return (
    <ul className="evidence-reference-list">
      {ids.map((id) => (
        <li key={id}>
          <a href={`#evidence-${id}`}>{id}</a>
        </li>
      ))}
    </ul>
  );
}

function GateView({ gate }: Readonly<{ gate: EvidenceGateDecision | null }>) {
  if (gate === null) {
    return <p className="gate-pending">Evidence gate not evaluated.</p>;
  }
  return (
    <section
      aria-label="Evidence gate decision"
      className={`gate gate-${gate.outcome.toLowerCase()}`}
    >
      <div className="gate-heading">
        <h4>Evidence gate</h4>
        <strong>{gate.outcome}</strong>
      </div>
      <p>
        Rules {gate.rulesVersion} · evaluated{" "}
        {new Date(gate.evaluatedAt).toLocaleString()}
      </p>
      {gate.reasons.length === 0 ? (
        <p>No refusal reasons.</p>
      ) : (
        <ul>
          {gate.reasons.map((reason) => (
            <li key={`${reason.code}-${reason.evidenceIds.join("-")}`}>
              <strong>{displayState(reason.code)}:</strong> {reason.detail}
              {reason.evidenceIds.length > 0
                ? ` (${reason.evidenceIds.join(", ")})`
                : ""}
            </li>
          ))}
        </ul>
      )}
      <p>
        Evaluated evidence: {gate.evaluatedEvidenceIds.join(", ") || "None"}
      </p>
      <p className="technical-id">
        Input {gate.inputFingerprint} · decision {gate.decisionFingerprint} ·
        schema {gate.schemaVersion}
      </p>
    </section>
  );
}

function Candidate({ candidate }: Readonly<{ candidate: RootCauseCandidate }>) {
  return (
    <li>
      <article className="diagnosis-card">
        <div className="diagnosis-heading">
          <div>
            <p className="eyebrow">RANK {candidate.rank}</p>
            <h3>{candidate.statement}</h3>
          </div>
          <span>
            {(candidate.confidenceBasisPoints / 100).toFixed(2)}% model
            confidence
          </span>
        </div>
        <p className="confidence-warning">
          Model confidence is non-authoritative and never replaces evidence or
          the deterministic gate.
        </p>
        <dl className="diagnosis-evidence-grid">
          <div>
            <dt>Supporting evidence</dt>
            <dd>{evidenceLinks(candidate.supportingEvidenceIds)}</dd>
          </div>
          <div>
            <dt>Counter-evidence</dt>
            <dd>{evidenceLinks(candidate.counterEvidenceIds)}</dd>
          </div>
          <div>
            <dt>Counter-evidence treatment</dt>
            <dd>
              {displayState(candidate.counterEvidenceTreatment)}
              {candidate.counterEvidenceExplanation
                ? ` — ${candidate.counterEvidenceExplanation}`
                : ""}
            </dd>
          </div>
          <div>
            <dt>Missing evidence</dt>
            <dd>{candidate.missingEvidence.join("; ") || "None"}</dd>
          </div>
          <div>
            <dt>Uncertainty</dt>
            <dd>{candidate.uncertainty}</dd>
          </div>
        </dl>
        <GateView gate={candidate.gate} />
      </article>
    </li>
  );
}

export function DiagnosisResults({
  result,
}: Readonly<{ result: DiagnosisResult | null }>) {
  return (
    <section aria-labelledby="diagnosis-results" className="diagnosis-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">EVIDENCE-BOUND OUTPUT</p>
          <h2 id="diagnosis-results">Ranked diagnosis</h2>
        </div>
        {result ? <span>{displayState(result.disposition)}</span> : null}
      </div>
      {result === null ? (
        <div className="panel">
          <p>No verified diagnosis report has been recorded.</p>
        </div>
      ) : (
        <>
          <div className="panel diagnosis-summary">
            <p>{result.explanation}</p>
            <p>
              Report-level missing evidence:{" "}
              {result.missingEvidence.join("; ") || "None"}
            </p>
            <p className="technical-id">
              Run {result.workflowRunId} · model call {result.modelCallId} ·
              report {result.reportFingerprint} · schema {result.schemaVersion}{" "}
              · produced {new Date(result.producedAt).toLocaleString()}
            </p>
          </div>
          {result.candidates.length === 0 ? (
            <p className="progress-notice">
              No root-cause candidate passed structured report validation.
            </p>
          ) : (
            <ol className="diagnosis-list">
              {result.candidates.map((candidate) => (
                <Candidate candidate={candidate} key={candidate.candidateId} />
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
