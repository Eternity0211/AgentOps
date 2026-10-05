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

Every node may also route to CANCELLED / END before invoking its service port.
```

Every node accepts the versioned `DiagnosisGraphState`. State retains identifiers, counters, hashes,
and phases only; model text, tool arguments/results, telemetry bodies, secrets, and Ground Truth are
never checkpoint fields. Each successful node transition increments the checkpoint sequence and
records a UTC timestamp.

State schema `1.3.0` retains the immutable query-fingerprint history and terminal `CANCELLED` phase
from earlier versions, and makes the exact Prompt ID, semantic version, and content fingerprint
mandatory. Migrations never infer or invent Prompt references or hashes for earlier calls.

## Ports and authority

`DiagnosisWorkflowServices` is the framework boundary implemented by later composition batches.
Its planning operation must first schema-validate and compile the model proposal, then durably store
the exact calls under the returned Tool Call IDs. The execution node reloads deterministic parallel
waves for those IDs and invokes each call only through the diagnosis-only Tool Gateway. It validates
that the waves contain every pending compiled call exactly once before starting them.

Before control handling and before every node-side service effect, the graph calls the required
Prompt-authorization port with the stable node operation identity. The production resolver loads
the exact tenant-scoped Registry version and current active version, requires them to be identical,
and then requires `ACTIVE` status, `DIAGNOSIS` purpose, and an exact content-fingerprint match to
state. There is no default or bypass implementation in `DiagnosisRuntimeContext`; composition that
does not supply the resolver cannot construct a runnable graph context. Prompt content remains in
the Registry and is never copied into graph state, checkpoints, interrupts, or observations.

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

## Durability boundary

The graph accepts the strict PostgreSQL checkpointer and has verified thread/run-correlated save,
history, restore, and completed-run resume behavior. Before every node-side service effect, a typed
control port may continue, pause, or cancel. Pause emits a content-free LangGraph interrupt bound
to the same checkpoint thread. Resume accepts only `RESUME` or `CANCEL`; invalid directives fail
closed. Cancellation transitions to `CANCELLED` and explicit conditional routing reaches `END`
without scheduling a later node or interrupting an effect already in progress.

Every service-port call receives a SHA-256 operation identity derived from tenant, workflow run,
graph version, checkpoint sequence, and node name. Per-tool identities also include the immutable
Tool Call ID. A service implementation must store and exactly replay the result for a repeated
operation identity, because a worker may fail after the effect but before its next checkpoint.
The graph therefore supplies replay identity without putting payloads into state. Worker-crash
continuation uses a checkpoint-aware runner: it starts with the supplied state only when the
thread has no checkpoint, otherwise it validates the persisted tenant/run/correlation identity and
invokes the graph with no replacement input. A newly constructed worker and PostgreSQL saver can
therefore continue the scheduled node from the last durable boundary.

Checkpoint observations are immutable content-free projections. They contain the hashed thread
ID, checkpoint and parent IDs, workflow run ID, graph phase, `READY`/`INTERRUPTED`/`FAILED`/`COMPLETE`
status, state sequence, bounded next-node names, task/interrupt counts, creation time, and a
canonical state fingerprint. Task errors, interrupt values, budgets, prompts, evidence, tool/model
payloads, and raw state are never copied into the projection. History reads are explicitly bounded
and omit LangGraph's internal pre-input checkpoint because it contains no Diagnosis state.

## Verification

Tests execute the compiled async graph through pass, one-replan-then-pass, explicit handoff, and
replan-budget-exhaustion routes. They prove same-wave tool concurrency, cumulative budgets,
reference-only output, transition sequencing, exact pending-call batches, duplicate refusal,
invalid result refusal, premature evidence-persistence refusal, and unsupported-route failure. A
topology contract enumerates every compiled node and edge, including every safe-boundary
cancellation edge, so an added or removed workflow route requires an explicit test review.
Interrupt tests additionally cover durable resume, resume-as-cancel, malformed directives,
cancellation before every service boundary, and stable identities for exact node replay.
PostgreSQL crash tests reconstruct the saver/graph at every durable node boundary and assert each
service operation occurs once. A separate failure-window test crashes after a plan effect commits
but before the node checkpoint and proves the repeated operation identity replays the stored result
instead of committing the effect twice. Prompt tests cover all seven node names, exact active
selection, tenant/version lookup, draft/evaluated/retired refusal, wrong-purpose and fingerprint
refusal, missing or changed active registration, and authorization ordering before controls and
effects.
