"""Fail-closed entry point for the isolated Ground Truth evaluator container."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MANIFEST_ROOT = Path("/evaluation/ground-truth")
CANARY_PATH = Path("/evaluation/canary/label.txt")
CREDENTIAL_PATH = Path("/run/secrets/ground_truth_access")
EXPECTED_SCENARIOS = {
    "bad-configuration",
    "db-pool-exhaustion",
    "downstream-latency",
    "http-500",
    "memory-leak",
    "redis-timeout",
}


class GroundTruthValidationError(RuntimeError):
    """Raised when the evaluation-only inputs do not satisfy their contract."""


def _read_required_text(path: Path, *, maximum_bytes: int) -> str:
    """Read a bounded non-empty UTF-8 file without including its value in errors."""
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise GroundTruthValidationError(
            f"required evaluation input unavailable: {path.name}"
        ) from error
    if not payload or len(payload) > maximum_bytes:
        raise GroundTruthValidationError(f"invalid evaluation input size: {path.name}")
    try:
        value = payload.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise GroundTruthValidationError(f"evaluation input is not UTF-8: {path.name}") from error
    if not value:
        raise GroundTruthValidationError(f"evaluation input is empty: {path.name}")
    return value


def _load_object(path: Path) -> dict[str, Any]:
    """Load one bounded JSON object with a payload-free diagnostic."""
    raw = _read_required_text(path, maximum_bytes=1_048_576)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise GroundTruthValidationError(f"invalid evaluation JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise GroundTruthValidationError(f"evaluation JSON must be an object: {path.name}")
    return value


def verify_inputs(
    manifest_root: Path = MANIFEST_ROOT,
    canary_path: Path = CANARY_PATH,
    credential_path: Path = CREDENTIAL_PATH,
) -> int:
    """Verify isolated mounts and return the number of scenario manifests."""
    _read_required_text(credential_path, maximum_bytes=4096)
    _read_required_text(canary_path, maximum_bytes=4096)
    schema = _load_object(manifest_root / "schema.json")
    if schema.get("additionalProperties") is not False:
        raise GroundTruthValidationError("Ground Truth schema must reject unknown fields")

    manifest_paths = sorted(manifest_root.glob("*.json"))
    scenarios = {
        value.get("scenario_id")
        for path in manifest_paths
        if path.name != "schema.json"
        for value in (_load_object(path),)
    }
    if scenarios != EXPECTED_SCENARIOS:
        raise GroundTruthValidationError(
            "Ground Truth scenario set does not match evaluator contract"
        )
    return len(scenarios)


def main() -> int:
    """Validate inputs without printing labels, canaries, credentials, or manifest content."""
    try:
        manifest_count = verify_inputs()
    except GroundTruthValidationError as error:
        print(f"[ground-truth] isolation-check failed: {error}")
        return 1
    print(f"[ground-truth] isolation-check passed manifests={manifest_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
