"""Validated simulator-side activation for implemented fault symptoms."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from agentops_incident_commander.simulator.app_types import ServiceName

FaultScenario = Literal["http-500", "db-pool-exhaustion", "redis-timeout"]
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
        if scenario not in {"http-500", "db-pool-exhaustion", "redis-timeout"}:
            raise ValueError("unsupported simulator fault scenario")
        expected_service: ServiceName = "inventory" if scenario == "redis-timeout" else "order"
        if service != expected_service:
            raise ValueError(f"selected fault can only target {expected_service.title()}")
        selected: FaultScenario
        if scenario == "http-500":
            selected = "http-500"
        elif scenario == "db-pool-exhaustion":
            selected = "db-pool-exhaustion"
        else:
            selected = "redis-timeout"
        return cls(scenario=selected, run_id=run_id)

    @property
    def forces_internal_error(self) -> bool:
        """Return the single typed effect rather than exposing free-form behavior."""
        return self.scenario == "http-500"

    @property
    def exhausts_database_pool(self) -> bool:
        """Select the bounded PostgreSQL pool-saturation behavior."""
        return self.scenario == "db-pool-exhaustion"

    @property
    def times_out_redis(self) -> bool:
        """Select a bounded Redis timeout without invoking the real client."""
        return self.scenario == "redis-timeout"
