"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  ApprovalRequestError,
  decideApproval,
  loadApproval,
  type ApprovalDetail as ApprovalRecord,
} from "@/lib/approvals";

function value(value: unknown) {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function nested(record: Record<string, unknown>, key: string) {
  return record[key] as Record<string, unknown>;
}

export function ApprovalDetail({
  approvalId,
}: Readonly<{ approvalId: string }>) {
  const [detail, setDetail] = useState<ApprovalRecord | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setLoadError(false);
    void loadApproval(approvalId, controller.signal).then(
      setDetail,
      (reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setLoadError(true);
        }
      },
    );
    return () => controller.abort();
  }, [approvalId, retry]);

  async function decide(form: FormData) {
    const current = detail as ApprovalRecord;
    const operation = String(form.get("operation")) as "approve" | "reject";
    const reason = String(form.get("reason") || "").trim();
    if (!reason) return;
    setBusy(true);
    setDecisionError(null);
    setNotice(null);
    try {
      const updated = await decideApproval(
        approvalId,
        operation,
        current.approval.version,
        reason,
      );
      setNotice(
        updated.status === "EXPIRED"
          ? "The Approval expired before the decision could be recorded."
          : `The Approval is now ${updated.status.toLowerCase()}.`,
      );
      setRetry((value) => value + 1);
    } catch (error) {
      const suffix =
        error instanceof ApprovalRequestError && error.requestId
          ? ` Request ID: ${error.requestId}.`
          : "";
      setDecisionError(
        `${error instanceof Error ? error.message : "Decision failed."}${suffix}`,
      );
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <main>
        <Link className="back-link" href="/approvals">
          ← Back to approvals
        </Link>
        <section className="panel" role="alert">
          <h1>Approval review unavailable</h1>
          <p>The server could not provide a verified review snapshot.</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            Retry
          </button>
        </section>
      </main>
    );
  }
  if (detail === null) {
    return (
      <main aria-busy="true">
        <p role="status">Loading verified Approval review…</p>
      </main>
    );
  }

  const approval = detail.approval;
  const parameters = nested(detail.proposal, "parameters");
  const verification = nested(detail.proposal, "verification_conditions");
  const failure = nested(detail.proposal, "failure_handling");
  const canDecide =
    approval.status === "PENDING" &&
    !approval.expired &&
    !approval.invalidated &&
    approval.separationOfDuties.satisfied;

  return (
    <main>
      <Link className="back-link" href="/approvals">
        ← Back to approvals
      </Link>
      <header className="page-heading approval-heading">
        <p className="eyebrow">IMMUTABLE HUMAN REVIEW</p>
        <h1>{approval.id}</h1>
        <div className="approval-badges">
          <span className={`risk risk-${approval.riskLevel.toLowerCase()}`}>
            {approval.riskLevel} RISK
          </span>
          <span>{approval.status}</span>
          <span>Proposal v{approval.proposalVersion}</span>
        </div>
      </header>

      {approval.invalidated ? (
        <p className="control-warning" role="alert">
          This Approval was invalidated by a material proposal revision. A new
          Approval is required; this record cannot authorize execution.
        </p>
      ) : null}
      {approval.expired ? (
        <p className="control-warning" role="status">
          This Approval has expired and cannot authorize execution.
        </p>
      ) : null}
      {!approval.separationOfDuties.satisfied ? (
        <p className="control-warning" role="alert">
          {approval.separationOfDuties.detail}
        </p>
      ) : null}
      {notice ? <p role="status">{notice}</p> : null}
      {decisionError ? <p role="alert">{decisionError}</p> : null}

      <section className="approval-layout" aria-label="Approval review">
        <article className="panel approval-proposal">
          <p className="eyebrow">PROPOSED RECOVERY</p>
          <h2>Rollback {value(parameters.service)}</h2>
          <dl className="approval-metadata">
            <div>
              <dt>Incident</dt>
              <dd>
                <Link href={`/incidents/${approval.incidentId}`}>
                  {approval.incidentId}
                </Link>
              </dd>
            </div>
            <div>
              <dt>Action</dt>
              <dd>{value(detail.proposal.action)}</dd>
            </div>
            <div>
              <dt>Proposer</dt>
              <dd>{approval.proposerActorId}</dd>
            </div>
            <div>
              <dt>Requested</dt>
              <dd>{new Date(approval.requestedAt).toLocaleString()}</dd>
            </div>
            <div>
              <dt>Expires</dt>
              <dd>{new Date(approval.expiresAt).toLocaleString()}</dd>
            </div>
            <div>
              <dt>Proposal fingerprint</dt>
              <dd className="technical-id">{approval.proposalFingerprint}</dd>
            </div>
          </dl>
          <h3>Evidence bindings</h3>
          <ul>
            <li>
              Introducing deployment:{" "}
              {value(parameters.introducing_deployment_evidence_id)}
            </li>
            <li>
              Current version:{" "}
              {value(
                nested(detail.proposal, "prerequisites")
                  .current_version_evidence_id,
              )}
            </li>
          </ul>
          <h3>Validation conditions</h3>
          <dl className="approval-metadata">
            {Object.entries(verification).map(([key, item]) => (
              <div key={key}>
                <dt>{key.replaceAll("_", " ")}</dt>
                <dd>{value(item)}</dd>
              </div>
            ))}
          </dl>
          <h3>Failure handling</h3>
          <p>
            {value(failure.route)} · {value(failure.max_rediagnosis_attempts)}{" "}
            bounded re-diagnosis attempts
          </p>
          <h3>Risk assumptions</h3>
          <ul>
            {(detail.proposal.risk_assumptions as unknown[]).map((item) => (
              <li key={value(item)}>{value(item)}</li>
            ))}
          </ul>
        </article>

        <article className="panel approval-policy">
          <p className="eyebrow">DETERMINISTIC POLICY</p>
          <h2>{detail.policy.outcome.replaceAll("_", " ")}</h2>
          <dl className="approval-metadata">
            <div>
              <dt>Environment</dt>
              <dd>{detail.policy.environment}</dd>
            </div>
            <div>
              <dt>Blast radius</dt>
              <dd>{detail.policy.blastRadius.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Maintenance window</dt>
              <dd>{detail.policy.maintenanceWindow.replaceAll("_", " ")}</dd>
            </div>
            <div>
              <dt>Policy version</dt>
              <dd>{detail.policy.policyVersion}</dd>
            </div>
          </dl>
          <h3>Policy reasons</h3>
          <ol className="policy-reasons">
            {detail.policy.reasons.map((reason) => (
              <li key={reason.code}>
                <strong>{reason.code.replaceAll("_", " ")}</strong>
                <span>{reason.detail}</span>
              </li>
            ))}
          </ol>
          <h3>Separation of duties</h3>
          <p>{approval.separationOfDuties.detail}</p>
          <p className="technical-id">
            Review fingerprint: {detail.reviewFingerprint}
          </p>
        </article>
      </section>

      {detail.invalidation ? (
        <section
          className="revision-section"
          aria-labelledby="proposal-revision"
        >
          <p className="eyebrow">MATERIAL CHANGE</p>
          <h2 id="proposal-revision">Immutable proposal diff</h2>
          <p>
            Changed by {detail.invalidation.invalidatedBy} at{" "}
            {new Date(detail.invalidation.invalidatedAt).toLocaleString()}.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Approved snapshot</th>
                  <th>Replacement</th>
                </tr>
              </thead>
              <tbody>
                {detail.proposalDiff.map((item) => (
                  <tr key={item.path}>
                    <th scope="row">{item.path}</th>
                    <td>{value(item.before)}</td>
                    <td>{value(item.after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section
        className="decision-section panel"
        aria-labelledby="human-decision"
      >
        <p className="eyebrow">HUMAN DECISION</p>
        <h2 id="human-decision">Approve or reject</h2>
        {canDecide ? (
          <form action={decide}>
            <label htmlFor="decision-reason">Decision reason</label>
            <textarea
              id="decision-reason"
              name="reason"
              required
              maxLength={512}
              rows={4}
              disabled={busy}
            />
            <div className="decision-actions">
              <button name="operation" value="approve" disabled={busy}>
                Approve proposal
              </button>
              <button
                className="secondary-action"
                name="operation"
                value="reject"
                disabled={busy}
              >
                Reject proposal
              </button>
            </div>
          </form>
        ) : (
          <p>No decision is available for this record.</p>
        )}
      </section>
    </main>
  );
}
