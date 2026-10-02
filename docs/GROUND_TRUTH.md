# Evaluation-only Ground Truth

The six versioned manifests under `evaluation/ground_truth/v1/` define evaluator labels and expected safe outcomes. They are data for scoring, never runtime configuration, agent context, evidence, or recovery authority.

`schema.json` is a closed JSON Schema: unknown top-level, evidence, deployment, and cleanup fields are rejected by contract. Every manifest records the root cause, symptoms, expected metric/log/trace/deployment evidence, automation eligibility and prerequisites, safe outcome or handoff reason, recovery action, deterministic verification, evaluator-only cleanup, and any future typed-tool requirement.

Only `http-500` and `memory-leak` are conditionally eligible for `rollback_service`; both require evidence of the introducing version and a server-resolved stable predecessor. The other four scenarios require human handoff and identify a future typed capability. `fault_clean` is evaluator maintenance after scoring and has `recovery_credit=false`.

The next isolation batch provides a separate Compose profile/path/network/credential boundary and leakage canaries. Until that boundary is verified, these manifests must not be mounted into or read by simulator or control-plane services.
