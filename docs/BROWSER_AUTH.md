# Browser authentication flow

The production API implements OIDC Authorization Code with PKCE as a server-owned browser flow.
No access token, ID token, Role, or Tenant claim is stored in browser-readable storage.

1. `GET /auth/login?tenant_id=...` validates the requested Tenant identifier, creates independent
   state, transaction, nonce, and PKCE verifier values, stores only the transaction needed for the
   short callback window, and redirects to the configured HTTPS authorization endpoint.
2. The browser receives a Secure, HttpOnly, SameSite=Lax `__Host-agentops_oidc` cookie. The raw
   transaction cookie is not included in the authorization URL; the state parameter is hash-bound
   to the same one-time database record.
3. `GET /auth/callback` atomically consumes that record, exchanges the code over HTTPS, verifies
   signature/issuer/audience/expiry/issued-at/nonce, and resolves `(issuer, subject)` through the
   active AgentOps Tenant membership. A replay, expired transaction, wrong browser, wrong nonce,
   inactive membership, or malformed provider response fails closed.
4. Success creates a random browser session and CSRF token. PostgreSQL stores only their SHA-256
   hashes. The raw session is Secure/HttpOnly/SameSite=Lax; the CSRF cookie is Secure/SameSite=Strict
   and must exactly match `X-CSRF-Token` on every POST, PUT, PATCH, or DELETE request.
5. `POST /auth/logout` requires the same CSRF binding, marks the database session revoked, and
   expires both browser cookies. Disabling the User, Tenant, or membership also invalidates session
   resolution immediately.

Session IDs are opaque and carry no Role data. Every authenticated request reloads the current
active membership, so a browser cannot retain removed authority until cookie expiry. Login
transactions and browser sessions have independently bounded TTLs. Provider redirects are never
followed by server-side HTTP clients; JWKS and token responses have time and byte limits.

The Next.js same-origin routes and visible sign-in/logout experience are tracked separately as
P14B2. Until that integration is present, these FastAPI routes can be exercised directly through a
deployment reverse proxy but the administration console still presents its generic access check.
