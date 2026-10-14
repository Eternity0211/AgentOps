# AgentOps administration console

This directory contains the deliberately small Next.js administration console. It is a view and
intent-capture layer only: backend authentication, RBAC, policy, approval, execution, and
verification remain authoritative.

## Toolchain

- Node.js `22.17.0` and npm `10.9.2` (also recorded in `.nvmrc` and `package.json`);
- exact dependency versions plus committed `package-lock.json`;
- ESLint, strict TypeScript, Vitest with 100% thresholds, and Playwright Chromium checks.

Install and verify from this directory:

```text
npm ci
npm run verify
npx playwright install chromium
npm run test:browser
```

`NEXT_PUBLIC_AGENTOPS_API_BASE_URL` defaults to same-origin `/api/v1`. When supplied, it must be a
clean absolute path or an HTTP(S) URL without credentials, query text, or fragments. The console
must never use this setting to infer authorization.

The shell requests `GET /session` below that base with same-origin credentials. It validates the
bounded Principal response before rendering business content and derives navigation only from the
permissions returned by the server. Hidden navigation is not authorization; backend routes remain
the enforcement boundary. Authentication, permission, network, and invalid-payload failures expose
an accessible retry state without attempting any control-plane action.

`/incidents` requests the tenant-scoped API projection in pages of 20. Exact severity, lifecycle
state, service, and opaque cursor values live in the URL; the browser never interprets a cursor or
derives authorization from list contents. Filters reset cursor history, and previous navigation is
available only for pages visited in the current client session. Loading, empty, and dependency
failure states remain read-only, while the table is horizontally contained on narrow screens.

`/incidents/{incident_id}` concurrently requests the tenant-scoped Incident, its first timeline
and Evidence pages, its latest Diagnosis progress projection, latest verified Diagnosis report,
and integrity-checked recovery projection. The lifecycle summary shows the
server-owned service, severity, state, optimistic version, and
opened/updated/closure/cancellation timestamps.
The investigation section shows server-persisted plan attempts, read-tool status and dependencies,
used/maximum/remaining budgets, bounded replan decisions, exhaustion, failures, and human handoff;
it does not reconstruct progress from the timeline. The ordered history distinguishes state
transitions from cancellation requests and preserves their actor, reason, version, correlation,
causation, and disposition metadata. Additional pages replay the server-provided opaque cursor
unchanged.

The Evidence section validates Incident ownership in every returned record before showing source,
normalized query, observation/collection times, immutable Artifact binding, hash, tool/parser/
normalizer/schema versions, deterministic quality reasons, expiry, trust, injection status, and
lineage. Artifact bytes are requested only after an explicit user action. The client checks the
Artifact ID and hash against Evidence plus the server's private/no-store, ETag, schema, media-type,
and redaction headers before rendering bounded `text/*` or JSON as escaped text. Binary content
and text over 256 KiB are verified but not rendered; expired Evidence disables retrieval, and
expiry, integrity, storage, and transport failures never expose partial content. Initial failures
fail the whole view closed; later-page failures preserve already validated records and offer a
read-only retry. Navigation or replacement requests abort stale reads, and no response path
mutates an Incident or derives workflow authority in the browser.

The ranked Diagnosis section keeps server rank order, links supporting and counter-evidence to
Evidence cards, preserves missing evidence and uncertainty, labels model confidence as
non-authoritative, and displays only deterministically matched Evidence Gate outcomes, reasons,
versions, times, and fingerprints. Empty reports remain explicit and invalid or corrupt response
shapes fail the complete read-only view closed.

The recovery section compares immutable executor before/after deployment snapshots and renders the
deterministic verifier's first and last values for error rate, P95 latency, health endpoint,
deployed version, and new alerts across the persisted stability window. Every signal links to its
Evidence record; PASS/FAIL reasons, fingerprints, and the exact closure, bounded re-diagnosis,
human-handoff, or deferred-cancellation transitions remain visible. A missing verifier result is
pending, never inferred success. The console always displays that `rollback_service` is itself the
recovery action, has no separate compensation authorization, and cannot automatically redeploy the
known faulty version after failed verification.

The agent-platform observability section uses the tenant-scoped
`/incidents/{incident_id}/platform-observability` projection. It shows content-free Prompt/model,
node, timing, correlation, request/response hash, exact token, and integer-cost metadata for a
bounded newest-first trace set. Costs stay separated by currency and unavailable metering remains
explicit. It also shows the latest fingerprint-verified durable Diagnosis progress checkpoint for
each bounded workflow run. The backend alone decides whether every displayed model call has its
single expected start event and, for terminal calls, finish event; missing/duplicate events and
truncation remain visible. Invalid trace, checkpoint, aggregate, or audit bindings fail the whole
read-only Incident view closed.

`/approvals` is available only when the authenticated session includes `approval:decide`. It pages
tenant-authorized Approval summaries and shows risk, status, expiry, invalidation, and server-owned
separation-of-duties feedback. `/approvals/{approval_id}` strictly validates the immutable proposal
and Policy projection, renders every Policy reason and verification/failure condition, and shows a
server-generated diff when a persisted material revision invalidates the original Approval.
Approve/reject forms submit a bounded reason, expected Approval version, correlation/causation
identities, and a fresh Idempotency Key. Buttons are absent for terminal, expired, invalidated, or
separation-restricted records. The browser waits for the authoritative response and reloads the
verified record; it never optimistically marks an Approval or invokes execution.
