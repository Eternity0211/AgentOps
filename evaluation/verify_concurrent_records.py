"""Offline ownership/content verifier; no approval or execution capability."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from evaluation.structured_model import fingerprint


def verify(root: Path) -> dict[str, Any]:
    def require(condition: bool, reason: str) -> None:
        if not condition:
            raise ValueError("CONCURRENT_" + reason)

    rows = json.loads((root / "sql-records.json").read_text(encoding="utf-8"))
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in root.glob("case-*-*.json")]
    ids = {c["incident_id"] for c in cases}
    require(len(ids) == len(cases) == 6, "CASE_IDENTITIES")
    require(all(re.fullmatch(r"concurrent-[0-9a-f]{20}", x) is not None for x in ids), "CASE_IDS")
    require({r["id"] for r in rows["incidents"]} == ids, "INCIDENT_SET")
    jobs = {r["incident_id"]: r for r in rows["jobs"]}
    require(set(jobs) == ids and len(rows["jobs"]) == 6, "JOB_SET")
    require(
        all(j["status"] == "COMPLETED" and j["attempt_count"] == 1 for j in jobs.values()),
        "JOB_COMPLETION",
    )
    evidence = {r["id"]: r for r in rows["evidence"]}
    require(len(evidence) == len(rows["evidence"]), "DUPLICATE_EVIDENCE")
    for e in evidence.values():
        incident = e["incident_id"]
        require(incident in jobs, "EVIDENCE_INCIDENT")
        job = jobs[incident]
        require(
            e["tenant_id"] == job["tenant_id"] and e["workflow_run_id"] == job["workflow_run_id"],
            "EVIDENCE_SCOPE",
        )
        digest, artifact = e["content_hash"], e["artifact_id"]
        require(
            re.fullmatch(r"[0-9a-f]{64}", digest) is not None
            and re.fullmatch(r"artifact-[0-9a-f]{64}", artifact) is not None,
            "ARTIFACT_ID",
        )
        store = root / "cases" / incident / "evidence"
        metadata = json.loads(
            (store / "metadata" / (artifact + ".json")).read_text(encoding="utf-8")
        )
        require(
            metadata["incident_id"] == incident
            and metadata["tenant_id"] == e["tenant_id"]
            and metadata["content_hash"] == digest,
            "ARTIFACT_SCOPE",
        )
        require(
            hashlib.sha256((store / "blobs" / digest[:2] / digest).read_bytes()).hexdigest()
            == digest,
            "ARTIFACT_HASH",
        )
    traces = {r["id"]: r for r in rows["model_call_traces"]}
    citations = 0
    for r in rows["diagnosis_reports"]:
        incident = r["incident_id"]
        require(incident in jobs, "REPORT_INCIDENT")
        job = jobs[incident]
        require(
            r["workflow_run_id"] == job["workflow_run_id"]
            and r["tenant_id"] == job["tenant_id"]
            and r["report"]["incident_id"] == incident,
            "REPORT_SCOPE",
        )
        trace = traces.get(r["model_call_id"])
        require(trace is not None, "REPORT_TRACE_MISSING")
        assert trace is not None
        require(
            trace["incident_id"] == incident
            and trace["workflow_run_id"] == r["workflow_run_id"]
            and trace["tenant_id"] == r["tenant_id"]
            and trace["status"] == "SUCCEEDED",
            "TRACE_SCOPE",
        )
        require(
            fingerprint(r["report"]) == r["report_fingerprint"] == trace["response_hash"],
            "REPORT_HASH",
        )
        for c in r["report"]["candidates"]:
            for ref in (*c["supporting_evidence_ids"], *c["counter_evidence_ids"]):
                e = evidence.get(ref)
                require(
                    e is not None
                    and e["incident_id"] == incident
                    and e["workflow_run_id"] == r["workflow_run_id"]
                    and e["tenant_id"] == r["tenant_id"],
                    "CITATION_SCOPE",
                )
                citations += 1
    require(not rows["action_executions"], "UNEXPECTED_EXECUTION")
    require(
        all(r["status"] == "PENDING" for r in rows["approvals"]), "UNEXPECTED_APPROVAL_DECISION"
    )
    return {
        "schema_version": "1.0.0",
        "incidents": len(ids),
        "jobs_completed_once": len(jobs),
        "reports_bound": len(rows["diagnosis_reports"]),
        "evidence_artifacts_verified": len(evidence),
        "citation_occurrences_verified": citations,
        "approvals": len(rows["approvals"]),
        "executions": 0,
        "ownership_verified": True,
        "scope": (
            "Structural ownership and content integrity only, "
            "not diagnostic correctness or human review"
        ),
    }
