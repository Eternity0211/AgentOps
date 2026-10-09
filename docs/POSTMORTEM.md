# Constrained Postmortem Drafting

The Phase 9 postmortem draft is a constrained LLM workflow node, not a third agent. It can run
only for a `CLOSED` Incident and cannot diagnose, change Incident state, execute tools, or author
new factual claims.

## Authority boundary

The application supplies a bounded set of immutable `ConfirmedPostmortemFact` values. Each fact
contains:

- a typed fact ID and one of `IMPACT`, `TIMELINE`, `ROOT_CAUSE`, `RECOVERY`, or `VERIFICATION`;
- a single-line, bounded statement that was already confirmed by a human or deterministic
  component;
- one or more Evidence IDs owned by the same tenant and Incident;
- confirmer identity, confirmation time, schema version, and a deterministic fingerprint.

The model receives those facts through a registered `POSTMORTEM` Prompt. Its strict output schema
contains only section kinds and fact IDs. The model may group and order facts, but cannot return
narrative text. The server rejects an outline that fabricates a reference, omits or duplicates a
fact, moves a fact to the wrong section, identifies another Incident, or violates the schema. The
final Markdown is rendered deterministically from the exact stored statements and Evidence IDs.

## Evidence resolution

Before a model call, every Evidence reference is resolved through the Evidence Store and immutable
Artifact storage. Generation fails closed unless the record:

- matches the requested tenant, Incident, and exact Evidence ID;
- is a current-Incident direct or derived observation, never historical memory or Ground Truth;
- was collected no later than the fact confirmation;
- has no prompt-injection classification;
- is unexpired and retains a valid Artifact content-hash binding.

The generator also requires `INCIDENT_READ` and `EVIDENCE_READ` for the tenant. Facts are rejected
when empty, duplicated, over the configured bounds, cross-scoped, or confirmed in the future.

## Prompt and model trace

Generation uses the exact active immutable Prompt version requested by the workflow. The Prompt
must have purpose `POSTMORTEM`, input/output schema compatibility `1.0.0`, and no incident-memory
context. Each attempted call records the Prompt fingerprint, request hash, workflow/Incident
identity, attempt, actor, correlation and causation IDs, terminal status, metering when available,
and response hash on success. Timeout, provider refusal, and invalid output remain distinct terminal
outcomes.

The credential-free deterministic mock covers valid, fabricated-reference, omitted-fact,
wrong-section, malformed, timeout, and refusal behavior.

## Output contract

`PostmortemDraft` is an immutable generated artifact in the domain layer. It binds tenant,
Incident, Prompt version and fingerprint, model-call trace, exact confirmed facts, generation time,
schema version, and a deterministic fingerprint. It exposes the ordered fact and Evidence IDs and
renders Markdown without model-authored factual prose.

Persistence of versioned human revisions, editor authorization, authorship, and revision audit is
the next Phase 9 batch. This draft contract does not claim that those capabilities are complete.

## Verification

Unit coverage exercises successful exact rendering and tracing; closed-Incident and authorization
requirements; Prompt/schema binding; fact bounds and scope; Evidence ownership, trust, freshness,
injection, expiry, and hash integrity; malformed and fabricated model output; timeout/refusal
classification; deterministic mock scenarios; and domain/schema invariants.
