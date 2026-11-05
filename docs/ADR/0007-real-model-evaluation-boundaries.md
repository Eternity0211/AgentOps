# ADR 0007: Real-model evaluation and simulated-operator boundaries

- Status: Accepted
- Date: 2026-11-03

## Decision

Keep experiment adapters in evaluation, outside runtime imports. Existing core tool versions
remain immutable. A new local experiment v2 catalog reuses read-tool names with explicit
local-only scope, bounded server-owned query windows and source/query provenance. No tool
accepts an endpoint, path, shell or deployment mutation. All model-selected calls compile
against this catalog and pass the existing Tool Gateway. This catalog is not advertised as
a production backend or a replacement for the core v1 contracts.

Simulated operators are deterministic evaluation fixtures, never agents or real approvers.
Their timings cannot substantiate human labor, UX or MTTR claims. Actual persisted recovery
still requires the existing independent human approval. Negative outcomes and unavailable
measurements remain visible. No model receives evaluation labels or decides execution success.

## Verification

Check exact catalog versions, local service allowlists, incident time windows, bounded calls,
source/argument schemas, actual gateway audit, secret redaction and injection quarantine.
Invalid plans dispatch zero calls. Simulated approval results and actual approval records must
have separate denominators and reports. Runtime imports cannot depend on evaluation modules.
