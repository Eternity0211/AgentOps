# ADR 0001: Agent Boundaries and Safety Chain

- Status: Accepted
- Date: 2026-10-01

## Context

Incident response benefits from hypothesis generation but infrastructure mutation requires deterministic authority, auditability, and reliable failure handling. Turning every component into an agent obscures responsibility and expands the attack surface.

## Decision

Use exactly two core decision agents: Diagnosis Agent and Remediation Agent. Postmortem drafting is a constrained node. Collection, evidence validation/gating, policy, execution, health verification, and rollback are deterministic components.

Enforce the non-bypassable chain: LLM proposal, schema validation, Policy Engine, human approval for medium/high risk, deterministic Executor, deterministic Health Verifier, then rollback when required.

## Consequences

Agent outputs must use versioned schemas and resolvable IDs. More code is required for deterministic routing and controls, but behavior is testable and authority is explicit. Adding another agent role or bypassing a link requires a superseding ADR and threat review.

## Rejected alternatives

- A broad multi-agent team: increased coordination cost and unclear authority.
- Direct tool execution from the LLM: unacceptable injection and replay risk.
- Confidence-only gating: cannot establish evidence integrity.

## Verification

Architecture dependency tests, tool capability tests, workflow-path tests, and audit assertions prove that no model node imports or invokes a write adapter and every mutation traverses all required gates.
