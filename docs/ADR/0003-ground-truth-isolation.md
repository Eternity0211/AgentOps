# ADR 0003: Ground Truth Isolation

- Status: Accepted
- Date: 2026-10-01

## Context

The simulator requires known causes and expected recovery to score diagnosis. If those labels reach the runtime or model context, evaluation becomes invalid.

## Decision

Store scenario Ground Truth in an evaluation-only location and expose it only to the evaluation harness. Runtime API, workers, simulator services, context builder, and model adapters receive no mount, credentials, API, or schema containing the labels. Evaluation compares runtime outputs after the run through identifiers managed outside the runtime.

## Consequences

Compose profiles/networks and CI permissions are more explicit. Scenario injection must return opaque run identifiers rather than labels. Debugging may require evaluator access, which remains separate and auditable.

## Rejected alternatives

- Hiding labels in prompts: not isolation.
- Keeping labels in the same runtime database with application filtering: vulnerable to query and implementation errors.

## Verification

Tests inspect runtime mounts/environment/database permissions and serialized model contexts, seed canary labels, and fail if any Ground Truth-only value or hash is visible.
