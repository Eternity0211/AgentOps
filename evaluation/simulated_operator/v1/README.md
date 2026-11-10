# Simulated operator review

This is a deterministic read-only backend review, not a human or an approval authority.
Its task success and timings cannot support human labor savings, UX or real MTTR claims.
The protocol is frozen before review measurements. Published measurements cover diagnostic archives and the persisted pending request.

`evaluation.simulated_review` now checks persisted report/trace bindings and current
Evidence/Artifacts, reruns Gate, and separately inspects a pending Approval review snapshot.
Task completion and evidence sufficiency are separate outputs; a correctly observed Gate
FAIL is not a failed read task. Missing bindings fail review. PostgreSQL integration uses controlled model outputs. Archived real-provider evidence is reported
separately in the [diagnosis review](../../results/simulated-operator/README.md) and
[pending review](../../results/simulated-operator/v2/README.md).

Archival provider review uses `evaluation.review_archive`: it checks the validated-output
hash, structured report and immutable Evidence manifests/Artifacts, then re-evaluates Gate
at the recorded capture clock. It does not fabricate SQL model-call records for standalone
runs, nor reconstruct missing report DTOs. Missing data fail the applicable review task.
