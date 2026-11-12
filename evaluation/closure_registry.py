"""Strict contract and invariants for the final comparative evaluation program."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictRegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class WorkStatus(StrEnum):
    COMPLETE = "COMPLETE"
    IN_PROGRESS = "IN_PROGRESS"
    PLANNED = "PLANNED"
    BLOCKED_EXTERNAL_DATA = "BLOCKED_EXTERNAL_DATA"


class SampleSizeStatus(StrEnum):
    FIXED_CENSUS = "FIXED_CENSUS"
    POWER_ANALYSIS_REQUIRED = "POWER_ANALYSIS_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ComparisonArm(StrictRegistryModel):
    arm_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    description: str = Field(min_length=1, max_length=500)


class SampleSizeDecision(StrictRegistryModel):
    status: SampleSizeStatus
    method: str = Field(min_length=1, max_length=500)
    fixed_pairs: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def fixed_census_has_size(self) -> SampleSizeDecision:
        if (self.status is SampleSizeStatus.FIXED_CENSUS) != (self.fixed_pairs is not None):
            raise ValueError("fixed census status and pair count must agree")
        return self


class ClosureExperiment(StrictRegistryModel):
    work_id: str = Field(pattern=r"^FC(?:[0-9]|1[0-3])$")
    title: str = Field(min_length=1, max_length=200)
    status: WorkStatus
    owner: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    prerequisites: tuple[str, ...]
    baseline: ComparisonArm
    candidate: ComparisonArm
    independent_variable: str = Field(min_length=1, max_length=500)
    metrics: tuple[str, ...] = Field(min_length=1)
    sample_size: SampleSizeDecision
    artifact_paths: tuple[str, ...] = Field(min_length=1)
    external_requirements: tuple[str, ...] = ()

    @model_validator(mode="after")
    def external_block_has_requirements(self) -> ClosureExperiment:
        if (self.status is WorkStatus.BLOCKED_EXTERNAL_DATA) != bool(
            self.external_requirements
        ):
            raise ValueError("external requirements must exist only for externally blocked work")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("metrics must be unique")
        return self


class LegacyMapping(StrictRegistryModel):
    legacy_id: str = Field(pattern=r"^LEGACY-[0-9]{2}$")
    summary: str = Field(min_length=1, max_length=500)
    resolution: str = Field(
        pattern=r"^(EXISTING_EVIDENCE|FC(?:[0-9]|1[0-3])(?:\+FC(?:[0-9]|1[0-3]))*)$"
    )
    evidence: tuple[str, ...] = Field(min_length=1)


class ClosureRegistry(StrictRegistryModel):
    schema_version: str = Field(pattern=r"^closure-registry/1\.0\.0$")
    generated_from: str = Field(pattern=r"^TODO\.md$")
    experiments: tuple[ClosureExperiment, ...] = Field(min_length=14, max_length=14)
    legacy_mappings: tuple[LegacyMapping, ...] = Field(min_length=16, max_length=16)

    @model_validator(mode="after")
    def complete_and_acyclic(self) -> ClosureRegistry:
        expected = {f"FC{index}" for index in range(14)}
        identifiers = [item.work_id for item in self.experiments]
        if set(identifiers) != expected or len(identifiers) != len(set(identifiers)):
            raise ValueError("registry must contain FC0 through FC13 exactly once")
        positions = {identifier: index for index, identifier in enumerate(identifiers)}
        for index, item in enumerate(self.experiments):
            if any(
                value not in expected or positions[value] >= index
                for value in item.prerequisites
            ):
                raise ValueError("prerequisites must reference earlier registered work")
        legacy_ids = [item.legacy_id for item in self.legacy_mappings]
        if len(legacy_ids) != len(set(legacy_ids)):
            raise ValueError("legacy mappings must be unique")
        return self


def load_closure_registry(path: Path) -> ClosureRegistry:
    return ClosureRegistry.model_validate_json(path.read_bytes())


def canonical_registry_bytes(registry: ClosureRegistry) -> bytes:
    return (
        json.dumps(registry.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
