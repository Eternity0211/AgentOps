"""Archive verification reads committed bytes, regardless of working-tree changes."""

import hashlib
import json
import subprocess
from pathlib import Path

from evaluation.git_archive_audit import audit


def test_git_archive_audit_uses_committed_objects_and_detects_mismatch(tmp_path: Path) -> None:
    git = ["git", "-c", f"safe.directory={tmp_path.as_posix()}", "-C", str(tmp_path)]
    subprocess.run([*git, "init"], check=True, capture_output=True)
    root = tmp_path / "evaluation/results/test/run"
    root.mkdir(parents=True)
    data = root / "data.bin"
    data.write_bytes(b"original")
    manifest = root / "file-hashes.json"
    manifest.write_text(
        json.dumps({"data.bin": hashlib.sha256(b"original").hexdigest()}), encoding="utf-8"
    )
    subprocess.run([*git, "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            *git,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "test: archive fixture",
        ],
        check=True,
        capture_output=True,
    )
    data.write_bytes(b"unrelated working tree change")
    result = audit(tmp_path)
    assert result["verified"] and result["checked"] == 1
    manifest.write_text(json.dumps({"data.bin": "0" * 64}), encoding="utf-8")
    subprocess.run([*git, "add", str(manifest)], check=True, capture_output=True)
    subprocess.run(
        [
            *git,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "test: mismatched digest",
        ],
        check=True,
        capture_output=True,
    )
    result = audit(tmp_path)
    assert not result["verified"]
    assert result["problems"][0]["kind"] == "hash_mismatch"
