from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_BINDINGS = {
    "666b769f": "evaluation/rcaeval/v1/protocol.json",
    "fb62ab10": "evaluation/results/safety-matrix/v2/run-001/result.json",
    "ee9e17f8": "evaluation/results/recall-development/v1/run-001/result.json",
    "6ab71ca6": "evaluation/results/rcaeval/v1/preflight-001.json",
}


def test_summary_and_scorecard_keep_missing_outcomes_explicit() -> None:
    summary = (ROOT / "docs/NEXT_EVALUATION_SUMMARY.md").read_text("utf-8")
    scorecard = (ROOT / "docs/PROJECT_EFFECT_SCORECARD.md").read_text("utf-8")
    for text in (summary, scorecard):
        assert "RCAEval" in text
        assert "not run" in text.lower()
        assert "FC5" in text
        assert "FC8" in text
        assert "NO_PROVEN_IMPROVEMENT" in text
    assert "0/5 unapproved execution" in summary
    assert "14/120 to 47/120" in summary
    assert "actually approved recovery" in summary


def test_phase_artifacts_match_their_published_git_objects() -> None:
    for revision, path in ARCHIVE_BINDINGS.items():
        committed = subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=D:/AgentOps",
                "show",
                f"{revision}:{path}",
            ],
            cwd=ROOT,
        )
        working = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        assert committed == working
