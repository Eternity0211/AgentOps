from __future__ import annotations

from evaluation.run_final_durability_probe import _binding, _principal


def test_durability_probe_uses_opaque_isolated_arm_identities() -> None:
    control = _binding("before-dispatch", "control")
    treatment = _binding("before-dispatch", "treatment")

    assert control["incident_id"] != treatment["incident_id"]
    assert control["workflow_run_id"] != treatment["workflow_run_id"]
    assert len(control["input_hash"]) == 64
    assert control["tenant_id"] == treatment["tenant_id"] == "tenant-durability"
    assert _principal().tenant_id.value == control["tenant_id"]
