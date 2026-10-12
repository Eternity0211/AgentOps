"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  incidentStates,
  loadIncidents,
  severities,
  type IncidentFilters,
  type IncidentPage,
} from "@/lib/incidents";

export function IncidentList() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryString = searchParams.toString();
  const filters = useMemo<IncidentFilters>(() => {
    const query = new URLSearchParams(queryString);
    return {
      severity: query.get("severity") || undefined,
      state: query.get("state") || undefined,
      service: query.get("service") || undefined,
      cursor: query.get("cursor") || undefined,
    };
  }, [queryString]);
  const [history, setHistory] = useState<(string | undefined)[]>([]);
  const [page, setPage] = useState<IncidentPage | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setPage(null);
    setError(false);
    void loadIncidents(filters, controller.signal).then(
      setPage,
      (reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError"))
          setError(true);
      },
    );
    return () => controller.abort();
  }, [filters, retry]);

  function navigate(next: IncidentFilters) {
    const query = new URLSearchParams();
    for (const key of ["severity", "state", "service", "cursor"] as const) {
      const value = next[key]?.trim();
      if (value) query.set(key, value);
    }
    const suffix = query.toString();
    router.push(suffix ? `${pathname}?${suffix}` : pathname, { scroll: false });
  }

  function apply(form: FormData) {
    setHistory([]);
    navigate({
      severity: String(form.get("severity") || "") || undefined,
      state: String(form.get("state") || "") || undefined,
      service: String(form.get("service") || "").trim() || undefined,
    });
  }

  return (
    <main>
      <header className="page-heading">
        <p className="eyebrow">INCIDENT OPERATIONS</p>
        <h1>Incidents</h1>
        <p>
          Tenant-scoped operational state from the authoritative control-plane
          API.
        </p>
      </header>
      <form action={apply} className="filter-bar" key={queryString}>
        <label>
          Severity
          <select name="severity" defaultValue={filters.severity ?? ""}>
            <option value="">All</option>
            {severities.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          State
          <select name="state" defaultValue={filters.state ?? ""}>
            <option value="">All</option>
            {incidentStates.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Service
          <input
            name="service"
            maxLength={128}
            pattern="[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}"
            defaultValue={filters.service ?? ""}
          />
        </label>
        <button type="submit">Apply filters</button>
      </form>
      {error ? (
        <section className="panel" role="alert">
          <h2>Incidents could not be loaded</h2>
          <p>No incident state was changed. Retry the current view.</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            Retry
          </button>
        </section>
      ) : page === null ? (
        <p aria-busy="true" role="status">
          Loading authorized incidents…
        </p>
      ) : page.items.length === 0 ? (
        <section className="panel">
          <h2>No incidents match these filters</h2>
        </section>
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <caption>{page.items.length} incidents on this page</caption>
              <thead>
                <tr>
                  <th>Incident</th>
                  <th>Service</th>
                  <th>Severity</th>
                  <th>State</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((incident) => (
                  <tr key={incident.id}>
                    <th scope="row">
                      <Link href={`/incidents/${incident.id}`}>
                        {incident.id}
                      </Link>
                    </th>
                    <td>{incident.service}</td>
                    <td>
                      <span
                        className={`severity ${incident.severity.toLowerCase()}`}
                      >
                        {incident.severity}
                      </span>
                    </td>
                    <td>{incident.state.replaceAll("_", " ")}</td>
                    <td>{new Date(incident.updatedAt).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav aria-label="Incident pages" className="pagination">
            <button
              type="button"
              disabled={history.length === 0}
              onClick={() => {
                const prior = history.at(-1);
                setHistory((values) => values.slice(0, -1));
                navigate({ ...filters, cursor: prior });
              }}
            >
              Previous
            </button>
            <button
              type="button"
              disabled={page.nextCursor === null}
              onClick={() => {
                setHistory((values) => [...values, filters.cursor]);
                navigate({
                  ...filters,
                  cursor: page.nextCursor as string,
                });
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
