# Clean-Machine Rehearsal

## Scope and acceptance criteria

This record covers the Phase 13 clean-machine rehearsal for AgentOps Incident Commander. The
acceptance boundary is a fresh GitHub-hosted checkout that can install the locked toolchains, run
the complete Python and console quality gates, reproduce the credential-free evaluation and mock
contracts, execute the deterministic release demo, build the locked runtime images, generate an
SBOM, and pass the configured security scans. Every named workflow must finish successfully; a
locally warm cache is not sufficient evidence for the Python offline-build path.

The implementation under rehearsal is commit
[`2b968acdf2362dad9dfc9c278cdc41b102c965ad`](https://github.com/Eternity0211/AgentOps/commit/2b968acdf2362dad9dfc9c278cdc41b102c965ad).
Its immediate parent
[`8298e7e37fd84513bb0fda3535c3e67c90be8491`](https://github.com/Eternity0211/AgentOps/commit/8298e7e37fd84513bb0fda3535c3e67c90be8491)
provides the cold-uv-cache proof for the unchanged Python dependency and build path. The final
commit changes only the Trivy workflow, its executable repository contract, tests, and supply-chain
documentation.

## Rehearsal environment

Versions below come from the linked job logs, not from the developer workstation.

| Component | Exact observed version |
| --- | --- |
| GitHub Actions runner | `2.338.2` |
| Runner image | `ubuntu-26.04`, image `20261025.179.1`, provisioner `20261021.618` |
| Git | `2.56.0` |
| Python | CPython `3.12.14` |
| uv | `0.13.4` |
| pytest | `9.1.1` |
| Docker Engine | `29.4.2` |
| Node.js | `22.17.0` |
| npm | `10.9.2` |
| Next.js | `16.4.1` |
| Browser | Chrome for Testing `156.0.8078.4`, Playwright Chromium build `1248` |
| Trivy | `0.76.1` |

The final Python run restored the uv download cache. The preceding successful Python run reported
`No GitHub Actions cache found` for the same lock and build path, installed Python 3.12.14 and all
locked groups, then completed quality, evaluation, mock mode, and the release demo. Both runs used
a new hosted job and checkout. Download caches are therefore distinguished from the checked-out
workspace and synchronized virtual environment rather than being described as a physically new
laptop.

## Reproduction procedure

The committed workflows are the executable procedure. For the Python boundary they run:

```text
uv python install 3.12.14
uv sync --frozen --all-groups
uv run --frozen python scripts/dev.py quality
uv run --frozen python scripts/dev.py eval --model mock
uv run --frozen python scripts/dev.py mock
uv run --frozen python scripts/dev.py demo
```

`quality` includes the lock check, formatting, lint, architecture and Compose contracts,
supply-chain contract, strict typing, the complete test suite, planning validation, and
`uv build --offline --no-sources --no-build-isolation`. The console job uses `npm ci`, the
repository `verify` script, an exact Playwright Chromium download, and the desktop/mobile browser
suite. The supply-chain job creates the CycloneDX repository SBOM, scans the checkout, builds both
digest-pinned runtime images, and scans both images with the pinned Trivy binary.

To repeat the evidence, push the target commit to a branch covered by the four workflows or use
their `workflow_dispatch` entry points. Preserve the commit SHA and workflow/job URLs because
runner images, vulnerability databases, and package-registry audit data can change after the run.

## Results and timings

All timestamps are GitHub API UTC timestamps. Durations are wall-clock differences at one-second
resolution and are observations of these hosted runs, not performance or reliability claims.

| Workflow/job | Result | Started | Finished | Duration |
| --- | --- | --- | --- | ---: |
| Python Quality / quality | success | `2026-11-02T13:50:04Z` | `2026-11-02T13:52:24Z` | 140 s |
| Console Quality / quality | success | `2026-11-02T13:49:54Z` | `2026-11-02T13:52:01Z` | 127 s |
| Supply Chain / scan-and-sbom | success | `2026-11-02T13:49:53Z` | `2026-11-02T13:51:17Z` | 84 s |
| Planning Docs / validate | success | `2026-11-02T13:49:53Z` | `2026-11-02T13:50:10Z` | 17 s |
| Parent Python cold-cache proof | success | `2026-11-02T11:42:00Z` | `2026-11-02T11:44:15Z` | 135 s |

The final Python job recorded 2,788 passing tests in 84.00 seconds and 100% statement/branch
coverage, validated 85 Markdown files and 19 coverage terms, and built both the source distribution
and wheel offline. The credential-free evaluation contract ran 110 passing tests. Mock mode used
`diagnosis-mock/1.0.0` with zero cost nanounits. The demo passed the six-scenario matrix (7 tests),
approved recovery and verification routes (4 tests), and audit/crash-resume matrix (40 tests).

The final console job recorded 317 passing unit tests with 100% statement, branch, function, and
line coverage, a successful Next.js production build, and 8 passing desktop/mobile Chromium tests.
The final supply-chain job generated the commit-bound
[CycloneDX SBOM artifact](https://github.com/Eternity0211/AgentOps/actions/runs/41456364754/artifacts/13147260669),
completed filesystem vulnerability/secret/misconfiguration scanning, built both runtime images,
and completed both image scans. Its logs confirm Trivy 0.76.1 and contain no policy-module skip for
an insufficient scanner version.

## Issues discovered and disposition

| Rehearsal finding | Disposition |
| --- | --- |
| The pinned `setup-node` v6.2.0 reference used a nonexistent SHA. | Replaced with the official full SHA in `ff6b094`; clean console checkout succeeds. |
| Linux mypy could not type-check Windows lock imports. | Added typed platform protocols and delayed imports in `ff6b094`. |
| Next.js 16.4.0 produced fixed HIGH/CRITICAL findings. | Upgraded and locked Next.js 16.4.1 in `ff6b094`; final image/filesystem scans pass the configured gate. |
| The development framework inserted a focusable element before the skip link. | Browser accessibility coverage now permits bounded framework focus while proving keyboard reachability in `ff6b094`. |
| A Windows locking branch was skipped on Linux and reduced clean-run coverage below 100%. | The test now exercises fake `msvcrt` acquire/release/contention behavior on every host in `0920bce`. |
| A cold uv cache lacked Hatchling for the offline package build. | Hatchling is an explicit locked development dependency from `f31cbd1`. |
| Isolated offline builds still tried to resolve a second Hatchling copy from an empty cache. | The build consumes the already synchronized frozen backend via `--no-build-isolation` from `8298e7e`; the no-cache hosted run succeeds. |
| A local scratch rehearsal timed out downloading `packaging==26.3`. | Classified as a local network failure; no success was claimed from that attempt. The hosted no-cache sync and build provide the reproducible evidence. |
| Trivy 0.70.0 skipped a policy module requiring at least 0.72.0. | Pinned Trivy 0.76.1 independently of the action and made the pin an executable repository invariant in `2b968ac`; the final log has no such skip. |
| Final `npm ci` reported 11 moderate and 1 high advisory across the full dependency graph. | The findings are in development/test tooling. A same-day `npm audit --omit=dev --json` reported zero production vulnerabilities; the mutable advisory database and dev-tool findings remain a documented limitation rather than a zero-vulnerability claim. |

## Limitations

- This is a fresh hosted checkout and process environment, not a physical new workstation, macOS
  rehearsal, or production deployment certification.
- The final run used download caches for uv and Trivy; the parent Python run separately proves the
  Python sync/build path with no matching uv cache. Registry, browser, image, and vulnerability
  database downloads still require network availability.
- The demo uses the local simulator, Testcontainers PostgreSQL, deterministic mock model, and
  repository fixtures. It does not enable a production model provider or production Kubernetes
  mutation.
- Job and step durations are single hosted observations. They are not latency SLOs, capacity
  measurements, or reliability statistics.
- A passing Trivy gate means no blocking fixed HIGH/CRITICAL result under the committed policy and
  the database available at run time. It is not proof of no vulnerability, and unfixed findings
  remain non-blocking as documented in the supply-chain policy.
- npm advisory counts are time-dependent. The final hosted log preserves its exact full-graph
  count; the production-only zero result was a separate same-day registry query and must be rerun
  for any later release.

## Evidence links

- [Final Python Quality run](https://github.com/Eternity0211/AgentOps/actions/runs/41456364604)
- [Final Console Quality run](https://github.com/Eternity0211/AgentOps/actions/runs/41456364615)
- [Final Supply Chain run](https://github.com/Eternity0211/AgentOps/actions/runs/41456364754)
- [Final Planning Docs run](https://github.com/Eternity0211/AgentOps/actions/runs/41456364717)
- [Cold-uv-cache Python proof](https://github.com/Eternity0211/AgentOps/actions/runs/41438852334)
- [Offline-build failure that exposed isolated-cache resolution](https://github.com/Eternity0211/AgentOps/actions/runs/41433516695)
- [Deterministic release demo contract](DEMO.md)
- [Supply-chain policy and scan boundary](SUPPLY_CHAIN.md)
- [Published evaluation methods and raw results](EVALUATION_REPORT.md)
