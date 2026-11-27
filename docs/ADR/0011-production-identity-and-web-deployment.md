# ADR 0011: Production OIDC identity and web deployment boundary

- Status: Accepted
- Date: 2026-11-27

## Context

The control plane already has fail-closed tenant-scoped RBAC and separate API, worker, and console
packages, but it intentionally shipped without a production authentication adapter or a combined
deployment. Browser callers cannot safely supply Actor, Tenant, or Role headers. Password storage
inside AgentOps would duplicate mature identity-provider controls and would enlarge the credential
and account-recovery surface.

## Decision

1. Use standards-based OIDC. The browser login uses Authorization Code with PKCE through a
   same-origin backend-for-frontend session. AgentOps does not store user passwords.
2. Verify tokens with an exact HTTPS issuer, audience, expiry, issued-at time, asymmetric algorithm
   allowlist, and a unique `kid` from bounded JWKS. Unknown, ambiguous, symmetric, malformed, or
   stale credentials fail closed.
3. Treat verified `(issuer, subject)` only as external identity. Tenant membership and Roles are
   server-owned versioned PostgreSQL records. Tenant and Role token claims are never authority.
4. Bind each request to one explicitly selected active Tenant membership. The API derives the
   Principal and continues to enforce tenant ownership and permissions at every use-case boundary.
5. Keep browser tokens out of JavaScript-readable storage. The console uses Secure, HttpOnly,
   SameSite cookies, CSRF protection for mutations, and same-origin API routing.
6. Deploy console/reverse proxy, API, worker, PostgreSQL, and observability as separate services.
   API and worker use separate process entry points and health checks; only the API accepts HTTP
   operator traffic. The worker claims durable PostgreSQL jobs and remains unable to authenticate
   browser requests.
7. Demo identities or header-based authentication are forbidden in the production composition.
   Local mock authentication, if retained for isolated tests, must be a different explicit
   composition and must fail closed by default.

The existing non-bypassable recovery chain is unchanged. Authentication creates no authority to
skip schema validation, Policy, independent Approval, deterministic execution, or verification.

## Consequences

- Deployments must provision an OIDC client, issuer/audience, redirect URI, and initial
  issuer/subject-to-tenant memberships.
- Disabling an AgentOps membership immediately removes application authority even if an IdP token
  remains cryptographically valid.
- IdP availability affects new sessions and token refresh. Existing requests still fail closed;
  the worker's durable processing does not depend on an interactive login.
- Tenant invitations, membership administration, session revocation, and key-cache policy become
  explicit application/deployment responsibilities rather than hidden browser behavior.

## Alternatives considered

- **Build username/password login in AgentOps.** Rejected because credential verification, MFA,
  account recovery, and breach response are not this product's domain.
- **Trust Tenant/Role token claims.** Rejected because IdP mapping mistakes or forged development
  claims could become control-plane authority and cross-tenant access.
- **Store bearer tokens in browser local storage.** Rejected because a script compromise could
  exfiltrate reusable control-plane credentials.
- **Run API and worker in one process.** Rejected because interactive request handling and durable
  work ownership have different lifecycle and exposure boundaries.

## Verification

- Unit tests cover issuer/audience/signature/expiry/claim/key failures, token bounds, and prove that
  Role/Tenant claims do not appear in the verified identity.
- PostgreSQL migration tests prove active identity membership resolution, cross-tenant denial,
  inactive-member denial, constrained Roles, and fail-closed corrupt assignments.
- Browser tests will prove redirect/callback/session/logout, CSRF denial, unauthenticated hiding,
  and server-derived navigation against the real API contract.
- Deployment tests will validate exact services, health checks, networks, secret mounts, non-root
  filesystems, API/worker separation, and absence of production authentication bypasses.
