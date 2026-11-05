"""Build advisory memory context only through authorized confirmed-incident retrieval."""

from __future__ import annotations

from typing import Any, Literal

from agentops_incident_commander.application.memory_retrieval import SimilarIncidentRetriever
from agentops_incident_commander.domain import IncidentMemorySearchQuery, Principal
from evaluation.observation_snapshot import sanitize_output


async def historical_context(
    retriever: SimilarIncidentRetriever,
    principal: Principal,
    query: IncidentMemorySearchQuery,
    *,
    excluded_incident_ids: frozenset[str],
) -> tuple[dict[str, Any], ...]:
    if query.current_incident_id.value not in excluded_incident_ids or query.max_results > 3:
        raise ValueError("memory evaluation scope/limit mismatch")
    references = await retriever.search(principal, query)
    if len(references) > query.max_results:
        raise ValueError("memory result budget exceeded")
    context = []
    seen = set()
    for item in references:
        if (
            item.incident_id.value in excluded_incident_ids
            or item.incident_id.value in seen
            or not query.freshness_cutoff <= item.closed_at <= query.requested_at
        ):
            raise ValueError("memory result leaks current/held-out or stale incident")
        seen.add(item.incident_id.value)
        content = sanitize_output(
            {
                "historical_incident_id": item.incident_id.value,
                "service": item.service,
                "root_cause_summary": item.root_cause_summary,
                "outcome": item.outcome,
                "outcome_summary": item.outcome_summary,
                "closed_at": item.closed_at.isoformat(),
                "historical_reference_only": True,
            }
        )
        if any(len(value) > 1024 for value in content.values() if isinstance(value, str)):
            raise ValueError("memory context text budget exceeded")
        context.append(content)
    return tuple(context)


class MemoryReplaySource:
    def __init__(
        self,
        retriever: SimilarIncidentRetriever,
        principal: Principal,
        query: IncidentMemorySearchQuery,
        excluded_incident_ids: frozenset[str],
        *,
        origin: Literal["CONFIRMED_DATABASE", "SIMULATED_FIXTURE"] = "CONFIRMED_DATABASE",
    ) -> None:
        self.retriever, self.principal, self.query = retriever, principal, query
        self.excluded = excluded_incident_ids
        self.origin = origin

    async def for_incident(self, incident_id: str) -> tuple[dict[str, Any], ...]:
        if self.query.current_incident_id.value != incident_id:
            raise ValueError("memory query does not match snapshot incident")
        references = await historical_context(
            self.retriever, self.principal, self.query, excluded_incident_ids=self.excluded
        )
        return tuple({**item, "history_origin": self.origin} for item in references)
