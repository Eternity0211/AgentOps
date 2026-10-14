"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  approvalStatuses,
  loadApprovals,
  type ApprovalPage,
} from "@/lib/approvals";

export function ApprovalList() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const queryString = params.toString();
  const filters = useMemo(() => {
    const query = new URLSearchParams(queryString);
    return {
      status: query.get("status") || undefined,
      cursor: query.get("cursor") || undefined,
    };
  }, [queryString]);
  const [page, setPage] = useState<ApprovalPage | null>(null);
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setPage(null);
    setError(false);
    void loadApprovals(filters.status, filters.cursor, controller.signal).then(
      setPage,
      (reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(true);
        }
      },
    );
    return () => controller.abort();
  }, [filters, retry]);

  function navigate(status?: string, cursor?: string) {
    const query = new URLSearchParams();
    if (status) query.set("status", status);
    if (cursor) query.set("cursor", cursor);
    router.push(query.size ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  }

  return (
    <main>
      <header className="page-heading">
        <p className="eyebrow">HUMAN RECOVERY CONTROL</p>
        <h1>Approvals</h1>
        <p>
          Review immutable remediation proposals and Policy decisions. Only the
          server can change Approval state.
        </p>
      </header>
      <form
        className="filter-bar approval-filter"
        action={(form) => {
          setHistory([]);
          navigate(String(form.get("status") || "") || undefined);
        }}
      >
        <label>
          Status
          <select name="status" defaultValue={filters.status ?? ""}>
            <option value="">All</option>
            {approvalStatuses.map((status) => (
              <option key={status}>{status}</option>
            ))}
          </select>
        </label>
        <button type="submit">Apply filter</button>
      </form>
      {error ? (
        <section className="panel" role="alert">
          <h2>Approvals could not be loaded</h2>
          <p>No Approval state was changed.</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            Retry
          </button>
        </section>
      ) : page === null ? (
        <p aria-busy="true" role="status">
          Loading authorized approvals…
        </p>
      ) : page.items.length === 0 ? (
        <section className="panel">
          <h2>No approvals match this filter</h2>
        </section>
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <caption>{page.items.length} approvals on this page</caption>
              <thead>
                <tr>
                  <th>Approval</th>
                  <th>Incident</th>
                  <th>Risk</th>
                  <th>Status</th>
                  <th>Expires</th>
                  <th>Control</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((approval) => (
                  <tr key={approval.id}>
                    <th scope="row">
                      <Link href={`/approvals/${approval.id}`}>
                        {approval.id}
                      </Link>
                      <small>
                        Proposal v{approval.proposalVersion} · Approval v
                        {approval.version}
                      </small>
                    </th>
                    <td>
                      <Link href={`/incidents/${approval.incidentId}`}>
                        {approval.incidentId}
                      </Link>
                    </td>
                    <td>
                      <span
                        className={`risk risk-${approval.riskLevel.toLowerCase()}`}
                      >
                        {approval.riskLevel}
                      </span>
                    </td>
                    <td>{approval.status.replaceAll("_", " ")}</td>
                    <td>{new Date(approval.expiresAt).toLocaleString()}</td>
                    <td>
                      {approval.invalidated
                        ? "Reapproval required"
                        : approval.expired
                          ? "Expired"
                          : approval.separationOfDuties.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav aria-label="Approval pages" className="pagination">
            <button
              type="button"
              disabled={history.length === 0}
              onClick={() => {
                const cursor = history.at(-1);
                setHistory((items) => items.slice(0, -1));
                navigate(filters.status, cursor);
              }}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={page.nextCursor === null}
              onClick={() => {
                setHistory((items) => [...items, filters.cursor]);
                navigate(filters.status, page.nextCursor as string);
              }}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </main>
  );
}
