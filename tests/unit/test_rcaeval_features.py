from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from evaluation.rcaeval_contract import FileBinding, Modality, TaskManifest
from evaluation.rcaeval_features import FeatureArm, build_localization_context

SERVICES = ("alpha", "bravo", "charlie", "delta", "echo")


def _write(path: Path, values: dict[str, list[object]]) -> FileBinding:
    pq.write_table(pa.table(values), path)
    return FileBinding(
        modality=Modality(path.stem),
        file_name=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        size_bytes=path.stat().st_size,
        available=True,
    )


def task_dir(tmp_path: Path) -> Path:
    root = tmp_path / "task"
    root.mkdir()
    metrics: dict[str, list[object]] = {"time": [100, 105, 110, 115]}
    for service in SERVICES:
        metrics[f"{service}_cpu"] = [1.0, 1.0, 1.0, 9.0] if service == "charlie" else [1.0] * 4
    bindings = (
        _write(root / "metrics.parquet", metrics),
        _write(
            root / "logs.parquet",
            {
                "timestamp": [105, 115, 116],
                "container_name": ["alpha", "charlie", "charlie"],
            },
        ),
        _write(
            root / "traces.parquet",
            {
                "startTimeMillis": [105_000, 115_000, 116_000],
                "serviceName": ["alpha", "charlie", "charlie"],
                "duration": [1.0, 20.0, 22.0],
                "statusCode": ["OK", "ERROR", "ERROR"],
            },
        ),
    )
    task = TaskManifest(
        schema_version="rcaeval-task/1.0.0",
        protocol_id="agentops-rcaeval-re2-service-localization-v1",
        protocol_sha256="1" * 64,
        case_id="re2-ob-0123456789abcdef",
        split_role="HOLDOUT",
        system="ONLINE_BOUTIQUE",
        observation_start_unix_s=100,
        injection_time_unix_s=110,
        observation_end_unix_s=120,
        candidate_services=SERVICES,
        files=bindings,
    )
    (root / "task.json").write_text(task.model_dump_json(indent=2), "utf-8")
    return root


def test_candidate_adds_label_free_before_after_features_within_budget(tmp_path: Path) -> None:
    root = task_dir(tmp_path)
    baseline = build_localization_context(root, FeatureArm.BASELINE)
    candidate = build_localization_context(root, FeatureArm.CANDIDATE)
    baseline_charlie = next(item for item in baseline.features if item.service == "charlie")
    candidate_charlie = next(item for item in candidate.features if item.service == "charlie")

    assert baseline_charlie.metric_delta is None
    assert baseline_charlie.error_delta is None
    assert candidate_charlie.metric_delta == 4.0
    assert candidate_charlie.log_delta == 2
    assert candidate_charlie.error_delta == 2
    assert candidate_charlie.duration_delta is None
    assert candidate.tool_calls == baseline.tool_calls == 14
    assert candidate.tool_calls <= 24
    assert "root_cause" not in candidate.model_dump_json()


def test_feature_builder_refuses_tampered_bound_telemetry(tmp_path: Path) -> None:
    root = task_dir(tmp_path)
    (root / "metrics.parquet").write_bytes(b"tampered")
    try:
        build_localization_context(root, FeatureArm.CANDIDATE)
    except ValueError as error:
        assert "binding" in str(error) or "hash" in str(error)
    else:  # pragma: no cover
        raise AssertionError("tampered telemetry was accepted")
