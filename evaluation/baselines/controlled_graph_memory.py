"""Controlled LangGraph baseline with historical-reference-only incident memory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from evaluation.baselines.controlled_graph import ControlledGraphDiagnosisSystem
from evaluation.contracts import (
    EvaluationCase,
    EvaluationContractError,
    content_sha256,
    load_json_object,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY = ROOT / "evaluation" / "memory" / "v1" / "references.json"
DEFAULT_MEMORY_PROMPT = ROOT / "evaluation" / "prompts" / "v1" / "controlled-graph-memory.json"
MEMORY_VERSION = "phase12-historical-memory-v1"
MEMORY_PROMPT_VERSION = "diagnosis-memory-v1.0.0"
_RECORD_FIELDS = frozenset(
    {
        "reference_id",
        "source_incident_id",
        "service",
        "closed_at",
        "root_cause_summary",
        "outcome_summary",
        "trust",
    }
)
_WORD = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset({"a", "an", "and", "after", "before", "its", "the", "to", "with"})


@dataclass(frozen=True, slots=True)
class HistoricalReference:
    reference_id: str
    source_incident_id: str
    service: str
    closed_at: datetime
    root_cause_summary: str
    outcome_summary: str
    trust: str

    @property
    def searchable_text(self) -> str:
        return " ".join((self.service, self.root_cause_summary, self.outcome_summary))

    @property
    def context(self) -> str:
        return (
            f"HISTORICAL_REFERENCE {self.reference_id}; service={self.service}; "
            f"root_cause={self.root_cause_summary}; outcome={self.outcome_summary}"
        )


class HistoricalMemoryIndex:
    """Versioned lexical retrieval over closed advisory records only."""

    def __init__(self, path: Path = DEFAULT_MEMORY) -> None:
        document = load_json_object(path)
        if frozenset(document) != {"schema_version", "memory_version", "records"} or (
            document["schema_version"] != "1.0"
            or document["memory_version"] != MEMORY_VERSION
            or not isinstance(document["records"], list)
            or not document["records"]
        ):
            raise EvaluationContractError("historical memory document is invalid")
        records: list[HistoricalReference] = []
        for value in document["records"]:
            if not isinstance(value, dict) or frozenset(value) != _RECORD_FIELDS:
                raise EvaluationContractError("historical memory record fields are invalid")
            try:
                closed_at = datetime.fromisoformat(value["closed_at"].replace("Z", "+00:00"))
            except (AttributeError, ValueError) as error:
                raise EvaluationContractError(
                    "historical memory closure time is invalid"
                ) from error
            strings = tuple(value[field] for field in _RECORD_FIELDS if field != "closed_at")
            if (
                closed_at.tzinfo is None
                or closed_at.utcoffset() != UTC.utcoffset(closed_at)
                or any(
                    not isinstance(item, str) or not item or len(item) > 1024 for item in strings
                )
                or value["trust"] != "HISTORICAL_REFERENCE"
            ):
                raise EvaluationContractError("historical memory record is not closed and advisory")
            records.append(
                HistoricalReference(
                    value["reference_id"],
                    value["source_incident_id"],
                    value["service"],
                    closed_at,
                    value["root_cause_summary"],
                    value["outcome_summary"],
                    value["trust"],
                )
            )
        identifiers = [record.reference_id for record in records]
        incidents = [record.source_incident_id for record in records]
        if (
            identifiers != sorted(identifiers)
            or len(identifiers) != len(set(identifiers))
            or len(incidents) != len(set(incidents))
        ):
            raise EvaluationContractError("historical memory records must be unique and ordered")
        self.records = tuple(records)
        self.fingerprint = content_sha256(document)

    @staticmethod
    def _tokens(value: str) -> frozenset[str]:
        return frozenset(_WORD.findall(value.casefold())) - _STOP_WORDS

    def retrieve(self, observation_text: str, *, limit: int = 2) -> tuple[HistoricalReference, ...]:
        if not 1 <= limit <= 20:
            raise EvaluationContractError("historical memory result limit is invalid")
        query = self._tokens(observation_text)
        ranked = sorted(
            (
                (len(query & self._tokens(record.searchable_text)), record.reference_id, record)
                for record in self.records
            ),
            key=lambda item: (-item[0], item[1]),
        )
        return tuple(record for score, _, record in ranked if score > 0)[:limit]


class ControlledGraphMemoryDiagnosisSystem(ControlledGraphDiagnosisSystem):
    """Add bounded historical context while preserving every controlled-graph boundary."""

    def __init__(
        self,
        *,
        memory_path: Path = DEFAULT_MEMORY,
        prompt_path: Path = DEFAULT_MEMORY_PROMPT,
    ) -> None:
        self.memory = HistoricalMemoryIndex(memory_path)
        super().__init__(
            prompt_path=prompt_path,
            _profile_kind="controlled-langgraph-memory",
            _prompt_version=MEMORY_PROMPT_VERSION,
            _prompt_interface="langgraph-memory",
            _memory_access=True,
        )

    def _historical_context(self, case: EvaluationCase) -> tuple[tuple[str, str], ...]:
        observation = " ".join(
            (
                case.observation.alert_summary,
                *(signal.summary for signal in case.observation.signals),
            )
        )
        references = self.memory.retrieve(observation)
        if any(reference.source_incident_id == case.case_id for reference in references):
            raise EvaluationContractError("historical retrieval returned the current case")
        return tuple((reference.reference_id, reference.context) for reference in references)
