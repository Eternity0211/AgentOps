"""Create and verify the immutable FC4 final-diagnosis result manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MANIFEST_NAME = "file-hashes.json"


def collect_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != MANIFEST_NAME
    }


def write_manifest(root: Path) -> Path:
    destination = root / MANIFEST_NAME
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(collect_hashes(root), stream, indent=2, sort_keys=True)
        stream.write("\n")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    write_manifest(args.results)


if __name__ == "__main__":  # pragma: no cover
    main()
