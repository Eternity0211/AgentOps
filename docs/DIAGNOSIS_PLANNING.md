# Deterministic diagnosis-plan compilation

The Diagnosis Agent may propose an investigation, but it does not select executable capabilities
or authorize dispatch. `compile_investigation_plan` converts the typed plan and one structured
proposal per step into an immutable, server-validated execution input. Compilation is
all-or-nothing and performs no tool call.

## Trust boundary

Every proposed call carries a step ID, exact tool name and semantic version, and canonical JSON
arguments. The compiler resolves that identity against the deployment-owned `ToolRegistry`; there
is no latest-version fallback. It then rejects disabled versions, every write tool, every tool above
`LOW` risk, oversized inputs, schema violations, and nested URL, absolute/parent path, shell-launch,
or control-character content. Consequently, model output cannot expand the supplied catalog or
substitute a raw query endpoint, command, or path.

The resulting `CompiledInvestigationPlan` contains only frozen values copied from the registered
definition and validated proposal. Later workflow nodes must dispatch these compiled calls rather
than reparsing or trusting the original model response. The Tool Gateway still repeats exact
version, access, schema, authorization, timeout, retry, result-limit, and audit checks at invocation;
plan compilation is an additional fail-closed boundary, not a replacement for the gateway.

Each compiled call also carries a lowercase SHA-256 query fingerprint over the exact tool name,
semantic version, and canonical structured arguments. Step IDs are deliberately excluded, so
renaming or reordering a step cannot disguise an equivalent query. JSON key order and whitespace
cannot affect the result. Tool-version or argument changes do affect it. Compilation rejects a
duplicate within the same plan and accepts durable fingerprint history from earlier replans so it
can reject an equivalent query before any dispatch.

## Hard budgets

The server supplies positive bounded limits for:

- total investigation steps;
- simultaneous calls in a parallel group;
- worst-case wall time;
- model tokens consumed while producing the plan; and
- model cost represented as integer nanounits.

Worst-case duration for a call includes every registered timeout attempt and maximum retry backoff.
Calls in the same `parallel_group` form one deterministic wave, whose duration is its slowest call;
wave durations are summed. Any step, parallelism, wall-time, token, or cost overrun rejects the
entire plan before dispatch. Usage and costs use integers so the decision is reproducible and does
not depend on floating-point rounding.

This compiler does not yet schedule calls, persist evidence, or decide whether to replan. Those
responsibilities belong to the durable LangGraph workflow and its deterministic routers.

## Verification

Unit tests cover stable plan-order compilation, parallel-wave and retry duration accounting,
immutability, every hard budget, malformed/non-canonical proposals, missing/duplicate step mapping,
unknown and disabled versions, write and non-low-risk tools, input size and schema failures, and
prompt-injection-like URL content. Query tests cover step-independent equivalence, version and
argument differences, same-plan duplicates, prior-replan duplicates, and malformed history. No
refusal path dispatches a tool.
