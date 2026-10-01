# Threat Model

## Assets and trust boundaries

Protected assets include infrastructure control, approvals, incident/evidence integrity, credentials, customer/telemetry data, prompt and policy definitions, audit history, model traces, and Ground Truth labels. Primary boundaries exist between users and API, API and worker, worker and models, Tool Gateway and observed systems, runtime and evaluation, console and authorization backend, and all services and persistence.

## Threats and required controls

| Threat | Required controls | Verification |
| --- | --- | --- |
| Prompt injection in logs/traces | Treat telemetry as untrusted data; delimit/quarantine prompt-like content; redact; tools selected from server catalog only. | Adversarial fixtures prove no tool/policy override. |
| Fabricated or swapped evidence | Immutable IDs/hashes, incident ownership, provenance, resolver-backed citations, gate checks. | Missing, cross-incident, altered, stale reference tests. |
| Approval bypass or confused deputy | Server-side RBAC/policy, separation of duties, proposal-bound approval hash, expiry, recheck at execution. | Direct endpoint, stale approval, modified plan, wrong-role tests. |
| Replay/duplicate execution | Scoped idempotency keys, unique DB constraint, target lock, stored result replay, nonce/timestamp where applicable. | Concurrent duplicate and worker-retry tests. |
| Excessive agent authority | Read-only diagnosis tools, strict action allowlist, no shell, network/service credentials isolated by component. | Capability and container-permission tests. |
| Sensitive-data leakage | Collection minimization, structured redaction, secret patterns, encrypted transport/storage, trace payload controls. | Seeded-secret canary tests and artifact scans. |
| Ground Truth leakage | Separate path/profile/network/credentials; runtime has no mount/API; dataset fields excluded from model context. | Container and context inspection tests. |
| Audit tampering | Append-only DB permissions, hash fields, immutable event IDs/order, restricted retention/admin operations. | Mutation-denied and sequence-integrity tests. |
| Compromised/stale worker | Short leases/heartbeat, execution-time authorization recheck, scoped credentials, revocation/cancel checks. | Crash/resume, lease takeover, cancellation race tests. |
| SSRF/path/target injection | Typed enumerated tool inputs, service registry resolution, deny raw URLs/paths/commands, egress allowlist. | Malformed and encoded bypass tests. |
| Resource/cost exhaustion | Per-incident step/token/time budgets, bounded retries/replans, concurrency/rate limits, payload caps. | Budget and load tests. |
| Model/provider compromise | Provider abstraction, minimal/redacted context, output schemas, distrust outputs, audit exact model/settings. | Invalid/malicious output contract tests. |
| Supply-chain compromise | Locked dependencies/images, scanning/SBOM plan, minimal images, reviewed update process. | CI scans and provenance report. |

## Safety invariants

1. No LLM output directly reaches a write adapter.
2. No client/UI assertion substitutes for backend authorization.
3. No confidence score substitutes for resolvable evidence.
4. No approval authorizes a materially different plan.
5. No workflow retry causes duplicate mutation.
6. No recovery is declared until deterministic observations pass for the stability window.
7. No runtime component can read evaluation Ground Truth.

Threat review is repeated when adding a write tool, external integration, authentication method, new trust boundary, or deployment target.
