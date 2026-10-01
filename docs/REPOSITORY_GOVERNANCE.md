# Repository CI and Branch Governance

This document distinguishes controls implemented in the repository from settings that require a GitHub administrator. It must not be used to claim that a remote protection rule is active without verifying that rule in GitHub.

## Implemented and locally verifiable

The repository contains:

- `.github/workflows/planning-docs.yml`, which runs on pushes to `main`, pull requests, and manual dispatch;
- a least-privilege workflow permission of `contents: read`;
- concurrency cancellation for superseded runs on the same ref;
- a five-minute job timeout;
- `scripts/check_planning_docs.ps1`, used by both local Windows development and the Ubuntu GitHub-hosted runner;
- validation for required planning files, local Markdown links, fenced blocks, trailing whitespace, exact EOF newline, merge-conflict markers, credential-shaped content, TODO requirement coverage, and non-goal checkbox misuse.

Run the same check locally:

```text
pwsh -NoProfile -File scripts/check_planning_docs.ps1
```

The initial status-check name is expected to appear as `Planning Docs / validate`. This expectation must be confirmed by a successful Actions run before it is selected as a required check. Phase 1A will add Python dependency, format, lint, type, and unit-test jobs; later phases add integration, security, frontend, and E2E jobs only when their corresponding code exists.

## Not configured or verified remotely

No GitHub ruleset or classic branch-protection rule has been configured or verified by this repository change. The repository currently permits the established atomic direct-push workflow. Documentation, a workflow file, or a successful check run does not prove that branch protection is active.

The following remain GitHub administrator actions:

- create and activate a ruleset targeting `main`;
- choose bypass actors, if any;
- select required status checks after those checks have run successfully;
- require pull requests, reviews, conversation resolution, signed commits, or deployments;
- verify deletion and force-push restrictions from the repository settings/API.

## Recommended staged policy

### Stage A — Current solo atomic-push workflow

Until Phase 1A CI exists and the project intentionally adopts pull requests, keep the current direct-push process and rely on repository instructions: no force push, no rewritten published history, atomic tested commits, and immediate push. Observe the `Planning Docs / validate` workflow and fix failures immediately.

Do not mark a required status check merely from its documented name; GitHub must first observe a successful check run. Do not enable a pull-request or review requirement that would make the approved solo workflow impossible without a deliberately documented bypass.

### Stage B — Recommended collaboration policy

After Phase 1A quality jobs have run successfully and development moves to feature branches/pull requests, create an active ruleset for `main` with:

- pull requests required before merge;
- `Planning Docs / validate` and the stable backend quality job required;
- branches required to be up to date before merge when queue/latency cost is acceptable;
- conversation resolution required;
- force pushes and branch deletion blocked;
- linear history required if the chosen merge strategy supports it;
- one approving review only when an independent reviewer is actually available;
- bypass permissions empty or limited to an explicitly audited recovery role.

Add frontend, integration, E2E, security, or deployment checks only after they are stable and their runtime is acceptable. A flaky or nonexistent required check can deadlock delivery.

## Verification record required after remote configuration

When a remote ruleset is eventually changed, record:

1. the date and actor;
2. target branch/pattern and enforcement status;
3. required check names and observed successful run URLs;
4. review, update, force-push, deletion, linear-history, and bypass settings;
5. the read-only command, API response, or settings screenshot used to verify the effective rule;
6. any repository-plan limitation or deliberate exception.

Until that evidence exists, project documentation must say “recommended” rather than “enabled.”

## References

- [GitHub: available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [GitHub: about protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [GitHub: actions/checkout releases](https://github.com/actions/checkout/releases)
