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
