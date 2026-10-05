# Diagnosis Agent Structured Schemas

Phase 6 defines strict, versioned Pydantic outputs for the only read-only decision agent. The
schemas constrain what a model may propose; they do not authorize a tool call, validate an Evidence
record, or pass the deterministic Evidence Gate.

`InvestigationPlan` version `1.0.0` contains at most sixteen uniquely identified steps. Each step
states a bounded single-line evidence objective, expected Evidence source type, earlier-step
dependencies, and a bounded parallel group. Dependencies must be unique, cannot self-reference,
and may only point backward. The schema deliberately has no command, URL, path, provider payload,
or arbitrary tool-argument field. Tool-catalog resolution and aggregate execution budgets are the
next separate control layer.

`DiagnosisReport` version `1.0.0` is either an ordered candidate report or one of three non-candidate
outcomes: more evidence required, refusal, or human handoff. Candidate ranks are consecutive and
IDs are unique. Each candidate has a bounded statement, at least one supporting Evidence ID,
disjoint counter-evidence IDs, explicit counter-evidence treatment and explanation, missing
evidence, uncertainty, and model confidence in basis points. Confidence remains metadata and never
changes Evidence Gate authority.

A report candidate converts deterministically to the existing `RootCauseEvidenceClaim`. Evidence
IDs are still resolved against immutable tenant/Incident-owned records by the deterministic Gate;
schema validity cannot make a fabricated reference true. Unresolved counter-evidence and declared
missing evidence remain visible to the Gate and therefore fail closed under the default rules.

Both models are frozen, strict, and reject extra fields. Tests cover bounds, unsafe multiline text,
duplicate and crossed references, invalid dependency graphs, rank/identity consistency, all
non-candidate dispositions, explicit counter-evidence handling, unknown fields, and exact Gate
claim conversion.

The credential-free [deterministic mock model](MOCK_MODEL.md) exercises both schemas with valid,
malformed, timeout, refusal, fabricated-reference, and injection-resistant scenarios. A fabricated
reference can satisfy syntax but remains unable to pass Evidence resolution or the deterministic
Gate.
