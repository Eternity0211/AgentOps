# Architecture Decision Records

ADRs capture decisions that constrain implementation. Accepted ADRs are immutable; changed decisions receive a new ADR that supersedes the old one.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-agent-boundaries-and-safety-chain.md) | Two decision agents and deterministic safety chain | Accepted |
| [0002](0002-langgraph-and-postgresql-durability.md) | LangGraph orchestration with PostgreSQL durability/queue | Accepted |
| [0003](0003-ground-truth-isolation.md) | Evaluation-only Ground Truth isolation | Accepted |
| [0004](0004-initial-remediation-scope.md) | Allow only typed `rollback_service` mutation initially | Accepted |

New ADRs use `NNNN-short-title.md` and contain context, decision, consequences, alternatives, and verification.
