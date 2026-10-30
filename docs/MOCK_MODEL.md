# Deterministic Diagnosis Mock Model

Phase 6 includes a credential-free mock adapter for testing Diagnosis plan and report handling. It
uses no network client, environment credential, clock, randomness, or provider SDK. The version is
fixed as `diagnosis-mock/1.0.0`; the same typed request, seed, node, and scenario always produce the
same strict output, usage counters, and response SHA-256.

The adapter supports six explicit scenarios:

- `VALID` returns a bounded two-step investigation plan and one evidence-linked candidate;
- `MALFORMED` returns deterministic provider-shaped data that fails the strict plan/report schema;
- `TIMEOUT` raises a typed timeout immediately, without wall-clock sleeping;
- `REFUSAL` produces a valid refused report and a typed planning refusal;
- `FABRICATED_REFERENCE` emits a syntactically valid but nonexistent Evidence ID so the existing
  deterministic Evidence Gate can demonstrate that schema validity and confidence grant no fact;
- `INJECTION_RESISTANT` receives adversarial context but produces the same server-owned bounded
  structure without copying or obeying that text.

Requests contain a bounded Incident ID, unique Evidence IDs, bounded context fragments, and a
non-negative deterministic seed. Context is treated as data only and never selects a scenario.
Results include the schema-validated object, mock version, deterministic input/output token counts,
zero integer cost, and a response hash. These values make the adapter suitable for workflow and
evaluation fixtures; they are not claims about real provider tokenization, latency, quality, or
cost. Production-provider invocation remains disabled.

The mock adapter does not bypass normal graph controls. A caller must still compile plans against
the Tool Registry, persist model-call trace metadata, resolve every Evidence reference, and pass
the deterministic Evidence Gate. Later Phase 6 composition connects these existing ports end to
end and requires approved Prompt Registry versions for every node.

## Runnable mock mode

Phase 13 exposes the adapter through the same fixed Python task runner used by Windows and CI:

```text
python scripts/dev.py mock
```

The command needs no provider account, API key, network access, database, Docker runtime, or model
download. It submits one fixed typed request containing adversarial untrusted context to both the
normal and injection-resistant scenarios, repeats planning and reporting, and fails unless the
strict outputs, usage, and response fingerprints are identical with zero cost. It prints only the
model version, canonical fingerprints, bounded token counters, and integer cost; no context or
output body is emitted. GitHub Actions runs the same command.

This is an executable local/CI verification mode, not a production provider integration or an
alternate authority path. It cannot call tools, policy, approval, Executor, or verifier components,
and its conclusions remain subject to the ordinary deterministic workflow gates whenever used by a
Diagnosis workflow.
