"""Validated simulator-side activation for implemented fault symptoms."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from agentops_incident_commander.simulator.app_types import ServiceName

FaultScenario = Literal["http-500", "db-pool-exhaustion"]
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")


@dataclass(frozen=True, slots=True)
class FaultBehavior:
    """One validated fault that may alter only its declared service path."""

    scenario: FaultScenario
    run_id: str

    @classmethod
    def from_environment(
        cls,
        service: ServiceName,
        environment: Mapping[str, str] | None = None,
    ) -> FaultBehavior | None:
        source = os.environ if environment is None else environment
        scenario = source.get("SIMULATOR_FAULT_SCENARIO")
        run_id = source.get("SIMULATOR_FAULT_RUN_ID")
        if scenario is None and run_id is None:
            return None
        if not scenario or not run_id:
            raise ValueError("fault scenario and run ID must be configured together")
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("invalid fault run ID")
        if scenario not in {"http-500", "db-pool-exhaustion"}:
            raise ValueError("unsupported simulator fault scenario")
        if service != "order":
            raise ValueError("selected fault can only target Order")
        selected: FaultScenario = "http-500" if scenario == "http-500" else "db-pool-exhaustion"
        return cls(scenario=selected, run_id=run_id)

    @property
    def forces_internal_error(self) -> bool:
        """Return the single typed effect rather than exposing free-form behavior."""
        return self.scenario == "http-500"

    @property
    def exhausts_database_pool(self) -> bool:
        """Select the bounded PostgreSQL pool-saturation behavior."""
        return self.scenario == "db-pool-exhaustion"
