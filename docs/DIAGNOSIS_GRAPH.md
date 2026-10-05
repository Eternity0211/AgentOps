# Bounded Diagnosis LangGraph

Phase 6 now has an executable LangGraph topology for the Diagnosis workflow. The graph orchestrates
typed ports and deterministic routes; it is not an additional agent and it does not grant LangGraph
or an LLM infrastructure authority.

## Topology

```text
START
  -> load_context
  -> plan
  -> execute_read_tools
  -> persist_evidence
  -> hypothesis
  -> evidence_gate
       -> COMPLETE / END
       -> plan (only while the replan budget remains)
       -> human_handoff / END
```

Every node accepts the versioned `DiagnosisGraphState`. State retains identifiers, counters, hashes,
and phases only; model text, tool arguments/results, telemetry bodies, secrets, and Ground Truth are
never checkpoint fields. Each successful node transition increments the checkpoint sequence and
records a UTC timestamp.

State schema `1.1.0` adds only the immutable query-fingerprint history. The migration from `1.0.0`
creates an empty history because older checkpoints never recorded this value; it cannot infer or
invent hashes for earlier calls.

## Ports and authority

`DiagnosisWorkflowServices` is the framework boundary implemented by later composition batches.
Its planning operation must first schema-validate and compile the model proposal, then durably store
the exact calls under the returned Tool Call IDs. The execution node reloads deterministic parallel
waves for those IDs and invokes each call only through the diagnosis-only Tool Gateway. It validates
that the waves contain every pending compiled call exactly once before starting them.

Calls in one wave run concurrently with structured cancellation; waves run in order. The graph
cannot persist evidence until every selected call is complete. The persistence port normalizes and
stores tool results and returns Evidence IDs, so the hypothesis node sees references rather than raw
tool output in graph state.

The hypothesis model returns a structured report through its port, but it cannot choose the next
route. `evaluate_evidence_gate` is a deterministic port. Its typed result can:

- pass and end the Diagnosis graph;
- request a replan, which the graph permits only while the hard replan budget remains; or
- require human handoff.

An exhausted replan request is converted to `HUMAN_HANDOFF` with a stable error code. Step, tool,
model-call, token, and integer-cost consumption is cumulative across replans and fails closed when a
maximum would be exceeded. Reference replay or duplication is rejected.

The plan node also compares every returned query fingerprint with durable prior history and with
the other queries in that plan. Any equivalent query routes directly to `HUMAN_HANDOFF` with
`REPEATED_EQUIVALENT_QUERY`; no Tool Call ID is accepted and no tool is dispatched. The rejected
planning model call, tokens, cost, and proposed-step attempt are still counted, preventing free
retry loops. The compiler performs the same duplicate check before a conforming service returns.

## Deferred durability work

This graph currently compiles without a checkpointer. PostgreSQL checkpoint storage, thread/run
correlation, pause/resume/cancel, idempotent node replay, crash continuation, and checkpoint
observability remain separate TODO batches. The service ports already use durable identifiers so
those capabilities can be added without placing content-bearing payloads in graph state.

## Verification

Tests execute the compiled async graph through pass, one-replan-then-pass, explicit handoff, and
replan-budget-exhaustion routes. They prove same-wave tool concurrency, cumulative budgets,
reference-only output, transition sequencing, exact pending-call batches, duplicate refusal,
invalid result refusal, premature evidence-persistence refusal, and unsupported-route failure.
