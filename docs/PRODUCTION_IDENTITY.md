# Production identity and tenant access

AgentOps delegates human authentication to a standard OIDC identity provider. It does not contain
a password database. A verified token establishes only the external `(issuer, subject)` pair; the
application then looks up an active local user and an active membership for the requested Tenant.

```text
OIDC signature + claims
        |
        v
Federated identity (issuer, subject)       token roles/tenant: ignored
        |
        v
active AgentOps user + active Tenant + active membership
        |
        v
Principal(actor_id, tenant_id, server-owned roles)
        |
        v
tenant ownership + permission + Policy + Approval checks
```

The identity schema contains four deliberately small records:

- `identity_users`: stable internal Actor identity and active state;
- `federated_identities`: exact OIDC issuer/subject binding to one Actor;
- `tenants`: server-owned tenant boundary and active state;
- `tenant_memberships`: versioned, active Role assignment for one Actor and Tenant.

An IdP administrator cannot grant AgentOps `ADMIN`, `APPROVER`, or another Tenant merely by adding
a claim. Membership changes happen through a separately authorized AgentOps administration path.
Until that path is implemented, bootstrap memberships are deployment-owned migration/seed data and
must never be accepted from a browser request.

The production browser flow is Authorization Code with PKCE. A same-origin session layer owns the
callback and keeps credentials in Secure, HttpOnly, SameSite cookies. Browser code calls the
same-origin `/api/v1` surface and receives only the server-derived session projection. Mutation
requests additionally require CSRF protection. Logout destroys the local session and, where the
provider supports it, initiates provider logout.

Required production configuration will include the exact HTTPS issuer, client ID/audience, client
secret or private-key client authentication where applicable, redirect URI, allowed signing
algorithms, session-encryption keys, and database URL. Values are deployment secrets; examples and
tests use non-secret placeholders. JWKS retrieval must be bounded by timeout, response size, cache
TTL, and known-host TLS validation. A refresh failure never falls back to unverified claims.

See [ADR 0011](ADR/0011-production-identity-and-web-deployment.md) for the decision and
[AUTHORIZATION.md](AUTHORIZATION.md) for the permission model. The implemented endpoint, cookie,
PKCE, replay, CSRF, and logout contract is documented in
[BROWSER_AUTH.md](BROWSER_AUTH.md).
