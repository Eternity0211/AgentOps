# Evaluation-only Ground Truth

The six versioned manifests under `evaluation/ground_truth/v1/` define evaluator labels and expected safe outcomes. They are data for scoring, never runtime configuration, agent context, evidence, or recovery authority.

`schema.json` is a closed JSON Schema: unknown top-level, evidence, deployment, and cleanup fields are rejected by contract. Every manifest records the root cause, symptoms, expected metric/log/trace/deployment evidence, automation eligibility and prerequisites, safe outcome or handoff reason, recovery action, deterministic verification, evaluator-only cleanup, and any future typed-tool requirement.

Only `http-500` and `memory-leak` are conditionally eligible for `rollback_service`; both require evidence of the introducing version and a server-resolved stable predecessor. The other four scenarios require human handoff and identify a future typed capability. `fault_clean` is evaluator maintenance after scoring and has `recovery_credit=false`.

## Isolation boundary

The evaluator is defined only in `compose.evaluation.yaml`, uses its own image, `evaluation` profile, internal `ground-truth` network, and `ground_truth_access` secret. It receives the manifests and leakage canary through evaluation-only read-only mounts. It has no runtime network, published port, persistent volume, runtime source tree, or control-plane/simulator credential.

The ordinary `compose.yaml` does not define or mount Ground Truth and does not receive its credential. `Dockerfile.simulator` copies only runtime source, while `Dockerfile.evaluator` copies only the evaluator verifier. The verifier bounds all reads and reports only a manifest count; label, canary, credential, and manifest content are never printed.

Create `secrets/ground-truth-access.txt` with a distinct local-only value and render or run the evaluator explicitly:

```text
docker compose -f compose.evaluation.yaml --profile evaluation config
docker compose -f compose.evaluation.yaml --profile evaluation run --rm ground-truth-evaluator
```

Repository tests seed the committed synthetic canary and assert that neither its value nor hash appears in runtime source, runtime Compose configuration, simulator image instructions, or model-context-capable paths. They also exercise fail-closed missing, empty, oversized, malformed, and incomplete evaluator inputs. This is isolation evidence, not a claim that a live evaluator container ran when Docker Engine is unavailable.
