"""Frozen RCAEval task export and bounded read-only telemetry contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SourcePin(StrictModel):
    repository: Literal["phamquiluan/RCAEval"]
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    index_path: Literal["cases.parquet"]
    index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license: Literal["MIT"]


class SplitContract(StrictModel):
    role: Literal["DEVELOPMENT", "HOLDOUT"]
    dataset: Literal["RE2-OB", "RE2-TT"]
    expected_cases: Literal[90]
    candidate_services: tuple[str, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def unique_candidates(self) -> SplitContract:
        if tuple(sorted(self.candidate_services)) != self.candidate_services:
            raise ValueError("candidate services must be sorted")
        if len(set(self.candidate_services)) != len(self.candidate_services):
            raise ValueError("candidate services must be unique")
        return self


class EvaluationBudget(StrictModel):
    max_model_calls_per_case: int = Field(ge=1, le=20)
    max_tool_calls_per_case: int = Field(ge=1, le=100)
    max_input_tokens_per_case: int = Field(ge=1, le=100_000)
    max_output_tokens_per_case: int = Field(ge=1, le=20_000)
    timeout_ms_per_case: int = Field(ge=1_000, le=600_000)


class ScoringContract(StrictModel):
    primary_metrics: tuple[Literal["service_top_1", "service_top_3"], ...]
    missing_prediction_policy: Literal["MISS"]
    invalid_prediction_policy: Literal["MISS"]
    unknown_case_policy: Literal["REJECT_RUN"]
    duplicate_case_policy: Literal["REJECT_RUN"]
    incompatible_label_policy: Literal["REFUSE_EQUIVALENCE"]
    confidence_level: float = Field(ge=0.95, le=0.95, allow_inf_nan=False)
    bootstrap_iterations: int = Field(ge=1_000, le=100_000)
    bootstrap_seed: int = Field(ge=0, le=2**32 - 1)
    minimum_relevant_effect: float = Field(gt=0, le=1)


class RcaEvalProtocol(StrictModel):
    schema_version: Literal["rcaeval-protocol/1.0.0"]
    protocol_id: Literal["agentops-rcaeval-re2-service-localization-v1"]
    source: SourcePin
    splits: tuple[SplitContract, SplitContract]
    budget: EvaluationBudget
    scoring: ScoringContract
    controls: tuple[
        Literal[
            "source_hash_preflight",
            "label_free_runtime",
            "read_only_telemetry",
            "paired_case_parity",
            "interleaved_arm_order",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def valid_splits_and_controls(self) -> RcaEvalProtocol:
        if [(item.role, item.dataset) for item in self.splits] != [
            ("DEVELOPMENT", "RE2-OB"),
            ("HOLDOUT", "RE2-TT"),
        ]:
            raise ValueError("development and holdout splits are frozen")
        if len(set(self.controls)) != len(self.controls):
            raise ValueError("controls must be unique")
        return self


class Modality(StrEnum):
    METRICS = "metrics"
    LOGS = "logs"
    TRACES = "traces"


class FileBinding(StrictModel):
    modality: Modality
    file_name: str = Field(pattern=r"^(metrics|logs|traces)\.parquet$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    available: bool

    @model_validator(mode="after")
    def modality_matches_file(self) -> FileBinding:
        if self.file_name != f"{self.modality.value}.parquet":
            raise ValueError("modality and file name differ")
        if self.available and (self.size_bytes == 0 or self.sha256 == "0" * 64):
            raise ValueError("available modality requires a non-empty content binding")
        if not self.available and (self.size_bytes != 0 or self.sha256 != "0" * 64):
            raise ValueError("missing modality must use the zero binding")
        return self


class TaskManifest(StrictModel):
    schema_version: Literal["rcaeval-task/1.0.0"]
    protocol_id: Literal["agentops-rcaeval-re2-service-localization-v1"]
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str = Field(pattern=r"^re2-(ob|tt)-[0-9a-f]{16}$")
    split_role: Literal["DEVELOPMENT", "HOLDOUT"]
    system: Literal["ONLINE_BOUTIQUE", "TRAIN_TICKET"]
    observation_start_unix_s: int = Field(ge=0)
    injection_time_unix_s: int = Field(ge=0)
    observation_end_unix_s: int = Field(ge=0)
    candidate_services: tuple[str, ...] = Field(min_length=5, max_length=5)
    files: tuple[FileBinding, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def valid_window_and_modalities(self) -> TaskManifest:
        if not (
            self.observation_start_unix_s
            <= self.injection_time_unix_s
            <= self.observation_end_unix_s
        ):
            raise ValueError("injection time must be inside the observation window")
        if tuple(item.modality for item in self.files) != tuple(Modality):
            raise ValueError("task files must list metrics, logs, then traces")
        return self


class Answer(StrictModel):
    case_id: str
    source_case: str
    root_cause_service: str
    fault: str


class AnswerSet(StrictModel):
    schema_version: Literal["rcaeval-answers/1.0.0"]
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    answers: tuple[Answer, ...]


class TaskIndex(StrictModel):
    schema_version: Literal["rcaeval-task-index/1.0.0"]
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tasks: tuple[TaskManifest, ...]


class TelemetryQuery(StrictModel):
    modality: Modality
    columns: tuple[str, ...] = Field(min_length=1, max_length=8)
    start_unix_s: int = Field(ge=0)
    end_unix_s: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)

    @model_validator(mode="after")
    def valid_query(self) -> TelemetryQuery:
        if self.end_unix_s < self.start_unix_s:
            raise ValueError("query end precedes start")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("query columns must be unique")
        return self


class TelemetryResult(StrictModel):
    schema_version: Literal["rcaeval-telemetry-result/1.0.0"]
    case_id: str
    modality: Modality
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool


def _canonical_bytes(value: BaseModel) -> bytes:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protocol_sha256(protocol: RcaEvalProtocol) -> str:
    return hashlib.sha256(_canonical_bytes(protocol)).hexdigest()


def load_protocol(path: Path = Path("evaluation/rcaeval/v1/protocol.json")) -> RcaEvalProtocol:
    return RcaEvalProtocol.model_validate_json(path.read_bytes())


def _case_id(dataset: str, source_case: str, revision: str) -> str:
    system = {"RE2-OB": "ob", "RE2-TT": "tt"}[dataset]
    suffix = hashlib.sha256(f"{revision}:{source_case}".encode()).hexdigest()[:16]
    return f"re2-{system}-{suffix}"


def _write_once(path: Path, content: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"export target already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _link_file(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"source telemetry must be a regular file: {source.name}")
    if target.exists():
        raise FileExistsError(f"export target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, target)


def export_tasks(
    *,
    protocol: RcaEvalProtocol,
    index_path: Path,
    telemetry_root: Path,
    output_root: Path,
) -> TaskIndex:
    """Export anonymous hard-linked tasks and a separate evaluator-only answer set."""
    if output_root.exists():
        raise FileExistsError(f"export root already exists: {output_root}")
    if _sha256(index_path) != protocol.source.index_sha256:
        raise ValueError("RCAEval index hash does not match the frozen source pin")
    table = pq.read_table(index_path)
    required = {
        "case",
        "dataset",
        "root_cause_service",
        "fault",
        "inject_time",
        "time_start",
        "time_end",
        "has_logs",
        "has_traces",
    }
    if not required.issubset(table.column_names):
        raise ValueError("RCAEval index is missing required columns")
    protocol_hash = protocol_sha256(protocol)
    tasks: list[TaskManifest] = []
    answers: list[Answer] = []
    for split in protocol.splits:
        subset = table.filter(pc.equal(table["dataset"], split.dataset))
        rows = sorted(subset.select(sorted(required)).to_pylist(), key=lambda row: row["case"])
        if len(rows) != split.expected_cases:
            raise ValueError(f"{split.dataset} case count differs from the frozen contract")
        for row in rows:
            source_case = str(row["case"])
            if "/" in source_case or "\\" in source_case or source_case in {".", ".."}:
                raise ValueError("unsafe source case identifier")
            case_id = _case_id(split.dataset, source_case, protocol.source.revision)
            source_dir = telemetry_root / source_case
            task_dir = output_root / "tasks" / case_id
            bindings: list[FileBinding] = []
            availability = {
                Modality.METRICS: True,
                Modality.LOGS: bool(row["has_logs"]),
                Modality.TRACES: bool(row["has_traces"]),
            }
            for modality in Modality:
                file_name = f"{modality.value}.parquet"
                source = source_dir / file_name
                available = availability[modality]
                if available:
                    _link_file(source, task_dir / file_name)
                    bindings.append(
                        FileBinding(
                            modality=modality,
                            file_name=file_name,
                            sha256=_sha256(source),
                            size_bytes=source.stat().st_size,
                            available=True,
                        )
                    )
                else:
                    if source.exists():
                        raise ValueError("index says modality is missing but a source file exists")
                    bindings.append(
                        FileBinding(
                            modality=modality,
                            file_name=file_name,
                            sha256="0" * 64,
                            size_bytes=0,
                            available=False,
                        )
                    )
            task = TaskManifest(
                schema_version="rcaeval-task/1.0.0",
                protocol_id=protocol.protocol_id,
                protocol_sha256=protocol_hash,
                case_id=case_id,
                split_role=split.role,
                system=("ONLINE_BOUTIQUE" if split.dataset == "RE2-OB" else "TRAIN_TICKET"),
                observation_start_unix_s=int(row["time_start"]),
                injection_time_unix_s=int(row["inject_time"]),
                observation_end_unix_s=int(row["time_end"]),
                candidate_services=split.candidate_services,
                files=tuple(bindings),
            )
            _write_once(task_dir / "task.json", task.model_dump_json(indent=2).encode() + b"\n")
            tasks.append(task)
            answers.append(
                Answer(
                    case_id=case_id,
                    source_case=source_case,
                    root_cause_service=str(row["root_cause_service"]),
                    fault=str(row["fault"]),
                )
            )
    index = TaskIndex(
        schema_version="rcaeval-task-index/1.0.0",
        protocol_sha256=protocol_hash,
        source_index_sha256=protocol.source.index_sha256,
        tasks=tuple(tasks),
    )
    answer_set = AnswerSet(
        schema_version="rcaeval-answers/1.0.0",
        protocol_sha256=protocol_hash,
        answers=tuple(answers),
    )
    _write_once(output_root / "task-index.json", index.model_dump_json(indent=2).encode() + b"\n")
    _write_once(
        output_root / "evaluator_only" / "answers.json",
        answer_set.model_dump_json(indent=2).encode() + b"\n",
    )
    return index


class ReadOnlyTelemetryAdapter:
    """Hash-verifying bounded Parquet reader with no caller-selected paths."""

    def __init__(self, task_dir: Path) -> None:
        self._task_dir = task_dir
        self.task = TaskManifest.model_validate_json((task_dir / "task.json").read_bytes())

    def columns(self, modality: Modality) -> tuple[str, ...]:
        """Return only the bound Parquet schema; never accept a caller-selected path."""
        binding = next(item for item in self.task.files if item.modality is modality)
        if not binding.available:
            return ()
        source = self._task_dir / binding.file_name
        if source.is_symlink() or source.stat().st_size != binding.size_bytes:
            raise ValueError("telemetry file binding is invalid")
        if _sha256(source) != binding.sha256:
            raise ValueError("telemetry file hash does not match the task binding")
        return tuple(pq.read_schema(source).names)

    def query(self, request: TelemetryQuery) -> TelemetryResult:
        if not (
            self.task.observation_start_unix_s
            <= request.start_unix_s
            <= request.end_unix_s
            <= self.task.observation_end_unix_s
        ):
            raise ValueError("query window is outside the task observation window")
        binding = next(item for item in self.task.files if item.modality is request.modality)
        if not binding.available:
            raise ValueError(f"{request.modality.value} modality is unavailable")
        source = self._task_dir / binding.file_name
        if source.is_symlink() or source.stat().st_size != binding.size_bytes:
            raise ValueError("telemetry file binding is invalid")
        if _sha256(source) != binding.sha256:
            raise ValueError("telemetry file hash does not match the task binding")
        schema = pq.read_schema(source)
        if request.modality is Modality.TRACES:
            time_column = "startTimeMillis"
            start_value = request.start_unix_s * 1_000
            end_value = request.end_unix_s * 1_000 + 999
        elif request.modality is Modality.LOGS:
            time_column = "timestamp"
            start_value = request.start_unix_s
            end_value = request.end_unix_s
        else:
            time_column = "time"
            start_value = request.start_unix_s
            end_value = request.end_unix_s
        selected = (time_column, *request.columns)
        if len(set(selected)) != len(selected) or any(
            name not in schema.names for name in selected
        ):
            raise ValueError("query requests an unknown or duplicate time column")
        table = pq.read_table(source, columns=list(selected))
        time_values = table[time_column]
        mask = pc.and_(
            pc.greater_equal(time_values, pa.scalar(start_value)),
            pc.less_equal(time_values, pa.scalar(end_value)),
        )
        filtered = table.filter(mask)
        truncated = filtered.num_rows > request.limit
        rows = tuple(filtered.slice(0, request.limit).to_pylist())
        return TelemetryResult(
            schema_version="rcaeval-telemetry-result/1.0.0",
            case_id=self.task.case_id,
            modality=request.modality,
            source_sha256=binding.sha256,
            columns=selected,
            rows=rows,
            truncated=truncated,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--telemetry-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    export_tasks(
        protocol=load_protocol(args.protocol),
        index_path=args.index,
        telemetry_root=args.telemetry_root,
        output_root=args.output_root,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
