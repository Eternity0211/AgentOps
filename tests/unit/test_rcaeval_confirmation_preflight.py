from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from evaluation.rcaeval_confirmation_preflight import Blocker, Status, audit
from evaluation.rcaeval_contract import SourcePin, load_protocol


def test_preflight_reports_every_missing_external_prerequisite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    report = audit(
        protocol_path=Path("evaluation/rcaeval/v1/protocol.json"),
        source_index=tmp_path / "cases.parquet",
        telemetry_root=tmp_path / "telemetry",
        task_export=tmp_path / "export",
    )
    assert report.status is Status.BLOCKED
    assert report.blockers == (
        Blocker.SOURCE_INDEX_MISSING,
        Blocker.TELEMETRY_ROOT_MISSING,
        Blocker.TASK_EXPORT_MISSING,
        Blocker.PROVIDER_CREDENTIAL_MISSING,
    )
    assert report.old_confirmation_outcomes_touched is False


def test_preflight_rejects_source_hash_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "present-but-not-recorded")
    index = tmp_path / "cases.parquet"
    index.write_bytes(b"wrong")
    (tmp_path / "telemetry").mkdir()
    report = audit(
        protocol_path=Path("evaluation/rcaeval/v1/protocol.json"),
        source_index=index,
        telemetry_root=tmp_path / "telemetry",
        task_export=tmp_path / "export",
    )
    assert Blocker.SOURCE_INDEX_HASH_MISMATCH in report.blockers
    assert report.source_index_hash_matches is False


def test_protocol_pin_cannot_be_replaced_by_a_same_size_file() -> None:
    protocol = load_protocol()
    replacement = b"0" * 31_157
    assert hashlib.sha256(replacement).hexdigest() != protocol.source.index_sha256
    assert protocol.source == SourcePin(
        repository="phamquiluan/RCAEval",
        revision="8b6c06a7a15bcecdbf70b611a13b789c5925dc17",
        index_path="cases.parquet",
        index_sha256="ec0008c90d0c97076bc98370ac824c3c5a49be95d00bd6d6044ea8061861d271",
        license="MIT",
    )
