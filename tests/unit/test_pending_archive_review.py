"""Check simulated review against the real archived pending request."""

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.review_pending_archive import review

PUBLISHED = Path("evaluation/results/simulated-operator/v2/pending-review.json")


def test_pending_archive_reproduces_review() -> None:
    record = json.loads(PUBLISHED.read_bytes())
    raw = Path(record["source"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record["source_sha256"]
    result = review(json.loads(raw))
    assert result == record["reviews"]
    assert len(result) == 1 and result[0]["pending_binding_verified"]
    assert result[0]["violations"] == ["ROLLBACK_INTRODUCING_REFERENCE_NOT_DEPLOYMENT"]
    assert not result[0]["approval_decided"] and not result[0]["recovery_executed"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proposal_fingerprint", "0" * 64),
        ("tenant_id", "foreign"),
        ("expires_at", "2000-01-01T00:00:00+00:00"),
    ],
)
def test_pending_archive_fails_changed_binding(field: str, value: str) -> None:
    record = json.loads(PUBLISHED.read_bytes())
    rows = json.loads(Path(record["source"]).read_bytes())
    rows["approvals"][0][field] = value
    result = review(rows)[0]
    assert not result["pending_binding_verified"]
    assert result["recommendation"] == "REJECT"
