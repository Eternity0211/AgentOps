# Supply-chain security

## Enforced baseline

The repository treats dependency identity, build inputs, and CI extensions as reviewed code:

- Python resolves through committed `uv.lock`; CI and `python scripts/dev.py quality` run
  `uv lock --check` and install only with `--frozen`.
- Console dependencies use exact versions in `package.json`, a version 3
  `package-lock.json`, and `npm ci` in CI.
- Every registry-provided Compose image and both Python base images retain a human-readable
  release tag and an immutable `sha256` manifest digest. Locally built images use explicit local
  tags and pinned bases. Fixed Debian security package versions bridge the interval before the
  upstream Python base digest is refreshed; the container scan verifies the final installed state.
- Every third-party GitHub Action is pinned to a full commit SHA with a release comment.
- The repository supply-chain contract rejects missing locks, floating images or actions,
  writable/privileged service definitions, Docker socket mounts, and locally built containers
  that do not drop all Linux capabilities. Both repository images run with fixed non-root numeric
  UID/GID values; the runtime uses read-only root filesystems and disables privilege escalation.

Run the deterministic local checks with:

```text
python scripts/dev.py supply-chain
python scripts/dev.py quality
```

The static contract does not claim that a pinned component is vulnerability-free. It proves that
reviewed identities cannot silently float between runs.

## CI scans and SBOM

The `Supply Chain / scan-and-sbom` job uses commit-pinned Trivy to scan the checked-out filesystem,
locked library graph, secrets, and configuration. It then builds both digest-pinned images and
scans their final OS and library contents. It fails on fixed HIGH or CRITICAL findings and retains
a CycloneDX repository SBOM for 30 days under a commit-bound artifact name. Unfixed findings remain
visible but do not block; changing that exception requires security review.

This is a repository SBOM, not yet a release-container SBOM. It does not scan Git history and does
not replace GitHub repository secret protection, host image scanning, or a release-signing system.
CI downloads the vulnerability databases at run time, so a scanner-service outage is an explicit
CI failure rather than a clean security result.

## Reviewed update policy

Dependency and image updates are grouped by trust boundary and reviewed at least monthly. A known
exploitable critical issue is triaged within one working day. Each update pull request must:

1. identify upstream release notes and the old/new version, digest, or Action commit;
2. regenerate only the relevant lock file and explain transitive changes;
3. run the full repository quality task plus the supply-chain workflow;
4. rebuild and exercise affected Compose profiles when an image or base changes;
5. record a time-bounded exception, owner, compensating control, and removal condition if a
   blocking finding cannot be fixed immediately.

Digest refreshes without a visible tag change are treated as real dependency updates. Major
versions, privilege changes, or new network/build trust boundaries require an ADR or threat-model
update before merge. Automated update pull requests may be added later, but they may never
auto-merge or bypass this review.

## Release provenance plan

The current repository does **not** claim signed release provenance. Before publishing a release,
the release workflow must be introduced in a separate reviewed batch and must:

- build each image from the tagged commit using the committed locks and digest-pinned bases;
- emit SPDX or CycloneDX SBOMs for each final image, not only the source tree;
- generate a GitHub artifact attestation or equivalent SLSA/in-toto statement binding commit,
  workflow identity, image digest, build parameters, and SBOM digest;
- sign immutable image digests with keyless OIDC identity, verify them before deployment, and
  retain verification instructions and policy;
- prohibit fork pull requests and untrusted code from receiving signing or publication authority.

Until those controls and a verification rehearsal exist, CI artifacts are evidence of scanning,
not a provenance or release-integrity guarantee.

## Permission exceptions

The simulator and evaluator images use numeric non-root users and drop all capabilities. Selected
upstream PostgreSQL, Redis, Prometheus, Loki, Tempo, Collector, and Grafana images retain their
vendor entrypoints and runtime users because their initialization and named-volume ownership are
image-specific. They still receive read-only roots, bounded resources, isolated networks, no
privilege escalation, explicit writable volumes/tmpfs, and no Docker socket. Moving an upstream
service to an overridden UID or capability set requires a live profile rehearsal proving startup,
health, persistence, and upgrade behavior.
