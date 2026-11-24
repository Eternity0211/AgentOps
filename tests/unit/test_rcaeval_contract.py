from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from evaluation.rcaeval_contract import (
    Modality,
    RcaEvalProtocol,
    ReadOnlyTelemetryAdapter,
    SourcePin,
    TelemetryQuery,
    export_tasks,
    load_protocol,
    protocol_sha256,
)


def _write_parquet(path: Path, values: dict[str, list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(values), path)


def _fixture_source(tmp_path: Path) -> tuple[Path, Path]:
    rows: list[dict[str, object]] = []
    root = tmp_path / "source"
    splits = {
        "RE2-OB": ("ob", "checkoutservice"),
        "RE2-TT": ("tt", "ts-auth-service"),
    }
    for dataset, (system, service) in splits.items():
        for index in range(90):
            case = f"re2{system}_{service}_cpu_{index + 1}"
            has_logs = not (dataset == "RE2-TT" and index == 0)
            rows.append(
                {
                    "case": case,
                    "dataset": dataset,
                    "root_cause_service": service,
                    "fault": "cpu",
                    "inject_time": 110,
                    "time_start": 100,
                    "time_end": 120,
                    "has_logs": has_logs,
                    "has_traces": True,
                }
            )
            case_dir = root / case
            _write_parquet(
                case_dir / "metrics.parquet",
                {"time": [100, 110, 120], f"{service}_cpu": [0.1, 0.9, 1.0]},
            )
            if has_logs:
                _write_parquet(
                    case_dir / "logs.parquet",
                    {"timestamp": [105, 115], "message": ["normal", "untrusted data"]},
                )
            _write_parquet(
                case_dir / "traces.parquet",
                {
                    "time": ["00:01", "00:01"],
                    "startTimeMillis": [105_000, 115_000],
                    "serviceName": [service, service],
                },
            )
    index_path = tmp_path / "cases.parquet"
    pq.write_table(pa.Table.from_pylist(rows), index_path)
    return index_path, root


def _fixture_protocol(index_path: Path) -> RcaEvalProtocol:
    protocol = load_protocol()
    source_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    return protocol.model_copy(
        update={
            "source": SourcePin(
                repository="phamquiluan/RCAEval",
                revision=protocol.source.revision,
                index_path="cases.parquet",
                index_sha256=source_hash,
                license="MIT",
            )
        }
    )


def test_frozen_protocol_pins_source_split_budget_and_incompatible_label_policy() -> None:
    protocol = load_protocol()

    assert protocol.source.revision == "8b6c06a7a15bcecdbf70b611a13b789c5925dc17"
    assert (
        protocol.source.index_sha256
        == "ec0008c90d0c97076bc98370ac824c3c5a49be95d00bd6d6044ea8061861d271"
    )
    assert [(split.role, split.dataset, split.expected_cases) for split in protocol.splits] == [
        ("DEVELOPMENT", "RE2-OB", 90),
        ("HOLDOUT", "RE2-TT", 90),
    ]
    assert protocol.scoring.incompatible_label_policy == "REFUSE_EQUIVALENCE"
    assert protocol.budget.max_tool_calls_per_case == 24
    assert len(protocol_sha256(protocol)) == 64


def test_export_is_label_free_binds_files_and_retains_missing_log(
    tmp_path: Path,
) -> None:
    index_path, source_root = _fixture_source(tmp_path)
    protocol = _fixture_protocol(index_path)
    output = tmp_path / "export"

    index = export_tasks(
        protocol=protocol,
        index_path=index_path,
        telemetry_root=source_root,
        output_root=output,
    )

    assert len(index.tasks) == 180
    answers_path = output / "evaluator_only" / "answers.json"
    answers = json.loads(answers_path.read_text(encoding="utf-8"))["answers"]
    missing_answer = next(
        item
        for item in answers
        if item["source_case"].endswith("cpu_1") and "tt_" in item["source_case"]
    )
    missing_task = next(item for item in index.tasks if item.case_id == missing_answer["case_id"])
    log_binding = next(item for item in missing_task.files if item.modality is Modality.LOGS)
    assert not log_binding.available
    assert not (output / "tasks" / missing_task.case_id / "logs.parquet").exists()

    task_text = (output / "tasks" / missing_task.case_id / "task.json").read_text(encoding="utf-8")
    assert missing_answer["source_case"] not in task_text
    assert '"fault"' not in task_text
    assert "root_cause_service" not in task_text
    assert answers_path.is_file()
    with pytest.raises(FileExistsError, match="export root already exists"):
        export_tasks(
            protocol=protocol,
            index_path=index_path,
            telemetry_root=source_root,
            output_root=output,
        )


def test_export_rejects_source_drift(tmp_path: Path) -> None:
    index_path, source_root = _fixture_source(tmp_path)
    protocol = load_protocol()

    with pytest.raises(ValueError, match="index hash"):
        export_tasks(
            protocol=protocol,
            index_path=index_path,
            telemetry_root=source_root,
            output_root=tmp_path / "export",
        )


def test_read_only_adapter_bounds_queries_and_rejects_tampering(tmp_path: Path) -> None:
    index_path, source_root = _fixture_source(tmp_path)
    protocol = _fixture_protocol(index_path)
    output = tmp_path / "export"
    index = export_tasks(
        protocol=protocol,
        index_path=index_path,
        telemetry_root=source_root,
        output_root=output,
    )
    task = index.tasks[0]
    task_dir = output / "tasks" / task.case_id
    metric = f"{task.candidate_services[0]}_cpu"
    adapter = ReadOnlyTelemetryAdapter(task_dir)

    result = adapter.query(
        TelemetryQuery(
            modality=Modality.METRICS,
            columns=(metric,),
            start_unix_s=100,
            end_unix_s=120,
            limit=2,
        )
    )

    assert result.columns == ("time", metric)
    assert len(result.rows) == 2
    assert result.truncated
    trace_result = adapter.query(
        TelemetryQuery(
            modality=Modality.TRACES,
            columns=("serviceName",),
            start_unix_s=100,
            end_unix_s=110,
            limit=2,
        )
    )
    assert trace_result.columns == ("startTimeMillis", "serviceName")
    assert len(trace_result.rows) == 1
    with pytest.raises(ValueError, match="outside"):
        adapter.query(
            TelemetryQuery(
                modality=Modality.METRICS,
                columns=(metric,),
                start_unix_s=99,
                end_unix_s=120,
                limit=2,
            )
        )
    (task_dir / "metrics.parquet").write_bytes(b"tampered")
    with pytest.raises(ValueError, match=r"binding is invalid|hash does not match"):
        adapter.query(
            TelemetryQuery(
                modality=Modality.METRICS,
                columns=(metric,),
                start_unix_s=100,
                end_unix_s=120,
                limit=2,
            )
        )
