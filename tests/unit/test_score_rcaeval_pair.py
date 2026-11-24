from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Literal

import pytest
from evaluation.rcaeval_contract import (
    Answer,
    AnswerSet,
    FileBinding,
    Modality,
    RcaEvalProtocol,
    TaskIndex,
    TaskManifest,
    load_protocol,
    protocol_sha256,
)
from evaluation.score_rcaeval_pair import (
    LocalizationRun,
    RunFailure,
    ServiceLocalizationOutput,
    score_pair,
)
from pydantic import ValidationError

TASK_HASH = hashlib.sha256(b"task-index").hexdigest()


def _fixture() -> tuple[RcaEvalProtocol, TaskIndex, AnswerSet]:
    protocol = load_protocol()
    binding = protocol_sha256(protocol)
    candidates = protocol.splits[0].candidate_services
    files = tuple(
        FileBinding(
            modality=modality,
            file_name=f"{modality.value}.parquet",
            sha256="1" * 64,
            size_bytes=10,
            available=True,
        )
        for modality in Modality
    )
    tasks = tuple(
        TaskManifest(
            schema_version="rcaeval-task/1.0.0",
            protocol_id=protocol.protocol_id,
            protocol_sha256=binding,
            case_id=f"re2-ob-{index:016x}",
            split_role="DEVELOPMENT",
            system="ONLINE_BOUTIQUE",
            observation_start_unix_s=100,
            injection_time_unix_s=110,
            observation_end_unix_s=120,
            candidate_services=candidates,
            files=files,
        )
        for index in range(2)
    )
    task_index = TaskIndex(
        schema_version="rcaeval-task-index/1.0.0",
        protocol_sha256=binding,
        source_index_sha256=protocol.source.index_sha256,
        tasks=tasks,
    )
    answers = AnswerSet(
        schema_version="rcaeval-answers/1.0.0",
        protocol_sha256=binding,
        answers=tuple(
            Answer(
                case_id=task.case_id,
                source_case=f"private-{index}",
                root_cause_service=candidates[index],
                fault="cpu",
            )
            for index, task in enumerate(tasks)
        ),
    )
    return protocol, task_index, answers


def _run(
    arm: Literal["BASELINE", "CANDIDATE"],
    outputs: Sequence[ServiceLocalizationOutput],
    failures: Sequence[RunFailure] = (),
) -> LocalizationRun:
    protocol = load_protocol()
    return LocalizationRun(
        schema_version="rcaeval-localization-run/1.0.0",
        run_id=f"{arm.lower()}-001",
        arm=arm,
        split_role="DEVELOPMENT",
        protocol_sha256=protocol_sha256(protocol),
        task_index_sha256=TASK_HASH,
        budget=protocol.budget,
        critical_safety_gate_passed=True,
        cost_latency_gate_passed=True,
        outputs=tuple(outputs),
        failures=tuple(failures),
    )


def test_typed_output_rejects_duplicate_services() -> None:
    with pytest.raises(ValidationError, match="ranked services must be unique"):
        ServiceLocalizationOutput(
            schema_version="service-localization-output/1.0.0",
            case_id="re2-ob-0000000000000001",
            ranked_services=("checkoutservice", "checkoutservice"),
        )


def test_pair_scorer_counts_failures_and_missing_as_misses() -> None:
    protocol, task_index, answers = _fixture()
    first, second = task_index.tasks
    candidates = first.candidate_services
    baseline = _run(
        "BASELINE",
        [
            ServiceLocalizationOutput(
                schema_version="service-localization-output/1.0.0",
                case_id=first.case_id,
                ranked_services=(candidates[1], candidates[0]),
            )
        ],
        [RunFailure(case_id=second.case_id, reason="TIMEOUT")],
    )
    candidate = _run(
        "CANDIDATE",
        [
            ServiceLocalizationOutput(
                schema_version="service-localization-output/1.0.0",
                case_id=first.case_id,
                ranked_services=(candidates[0],),
            )
        ],
    )

    result = score_pair(
        protocol=protocol,
        task_index=task_index,
        task_index_hash=TASK_HASH,
        answers=answers,
        baseline=baseline,
        candidate=candidate,
    )

    assert result.baseline.top_1_correct == 0
    assert result.baseline.top_3_correct == 1
    assert result.baseline.failures == 1
    assert result.candidate.top_1_correct == 1
    assert result.candidate.missing == 1
    assert [metric.metric_id for metric in result.comparison.metrics] == [
        "service_top_1",
        "service_top_3",
    ]
    assert all(metric.pair_count == 2 for metric in result.comparison.metrics)


@pytest.mark.parametrize("mutation", ["budget", "task_hash", "unknown_service"])
def test_pair_scorer_rejects_parity_and_candidate_set_drift(mutation: str) -> None:
    protocol, task_index, answers = _fixture()
    task = task_index.tasks[0]
    output = ServiceLocalizationOutput(
        schema_version="service-localization-output/1.0.0",
        case_id=task.case_id,
        ranked_services=(task.candidate_services[0],),
    )
    baseline = _run("BASELINE", [output])
    candidate = _run("CANDIDATE", [output])
    if mutation == "budget":
        candidate = candidate.model_copy(
            update={"budget": protocol.budget.model_copy(update={"max_tool_calls_per_case": 23})}
        )
    elif mutation == "task_hash":
        candidate = candidate.model_copy(update={"task_index_sha256": "2" * 64})
    else:
        candidate = candidate.model_copy(
            update={
                "outputs": (output.model_copy(update={"ranked_services": ("not-a-candidate",)}),)
            }
        )

    with pytest.raises(ValueError):
        score_pair(
            protocol=protocol,
            task_index=task_index,
            task_index_hash=TASK_HASH,
            answers=answers,
            baseline=baseline,
            candidate=candidate,
        )
