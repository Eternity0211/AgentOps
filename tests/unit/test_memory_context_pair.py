from __future__ import annotations

from evaluation.score_memory_context_pair import claims_sustained_memory


def test_memory_claim_classifier_requires_explicit_bounded_language() -> None:
    assert claims_sustained_memory(
        {"candidates": [{"statement": "Order has sustained memory retention after GC"}]}
    )
    assert not claims_sustained_memory(
        {"candidates": [{"statement": "Order was deployed and memory evidence is insufficient"}]}
    )
    warmup = {"candidates": [{"statement": "Normal warmup memory retention, not a leak"}]}
    assert claims_sustained_memory(warmup, profile="v1")
    assert not claims_sustained_memory(warmup, profile="v2")
