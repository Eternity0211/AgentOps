"""Read Git blobs directly so checkout line endings cannot hide archive hash failures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def audit(repo: Path, revision: str = "HEAD") -> dict[str, Any]:
    git = ["git", "-c", f"safe.directory={repo.resolve().as_posix()}", "-C", str(repo)]
    resolved = subprocess.check_output([*git, "rev-parse", "--verify", revision], text=True).strip()
    paths = subprocess.check_output(
        [*git, "ls-tree", "-r", "--name-only", resolved, "--", "evaluation/results"], text=True
    ).splitlines()
    manifests = [p for p in paths if p.endswith("/file-hashes.json")]
    checked = 0
    problems = []
    with subprocess.Popen(
        [*git, "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        input_stream, output_stream = process.stdin, process.stdout
        assert input_stream is not None and output_stream is not None

        def blob(path: str) -> bytes | None:
            if any(v in path for v in ("\n", "\r")):
                raise ValueError("invalid archive path")
            input_stream.write(f"{resolved}:{path}\n".encode())
            input_stream.flush()
            header = output_stream.readline().decode().strip().split()
            if header and header[-1] == "missing":
                return None
            if len(header) != 3 or header[1] != "blob":
                raise ValueError("invalid Git blob response")
            size = int(header[2])
            data = output_stream.read(size)
            if len(data) != size or output_stream.read(1) != b"\n":
                raise ValueError("truncated Git blob response")
            return data

        try:
            for manifest in manifests:
                payload = blob(manifest)
                assert payload is not None
                hashes = json.loads(payload)
                if not isinstance(hashes, dict):
                    raise ValueError("archive manifest must be an object")
                for name, expected in hashes.items():
                    if (
                        not isinstance(name, str)
                        or Path(name).is_absolute()
                        or ".." in Path(name).parts
                    ):
                        raise ValueError("invalid archive entry path")
                    if (
                        not isinstance(expected, str)
                        or re.fullmatch(r"[0-9a-f]{64}", expected) is None
                    ):
                        raise ValueError("archive digest must be a string")
                    path = (Path(manifest).parent / name).as_posix()
                    data = blob(path)
                    checked += 1
                    if data is None or hashlib.sha256(data).hexdigest() != expected:
                        problems.append(
                            {
                                "manifest": manifest,
                                "file": name,
                                "kind": "missing" if data is None else "hash_mismatch",
                            }
                        )
        finally:
            input_stream.close()
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
    return {
        "revision": resolved,
        "manifests": len(manifests),
        "checked": checked,
        "problems": problems,
        "verified": bool(manifests) and not problems,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    result = audit(args.repo, args.revision)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["verified"] else 1)


if __name__ == "__main__":
    main()
