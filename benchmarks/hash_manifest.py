"""Write or verify a SHA-256 manifest of every file under a benchmark
dataset root, proving the tool never modifies scanned files.

Not part of the imageset_guard package -- a development-only tool.

Usage:
    python benchmarks/hash_manifest.py <root> write|verify <manifest_path>
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    root, mode, manifest_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    files = sorted(p for p in root.rglob("*") if p.is_file())

    if mode == "write":
        with manifest_path.open("w", encoding="utf-8") as out:
            for p in files:
                out.write(f"{file_hash(p)}  {p.relative_to(root).as_posix()}\n")
        print(f"Wrote manifest for {len(files)} files to {manifest_path}")
        return

    if mode == "verify":
        expected = {}
        with manifest_path.open(encoding="utf-8") as f:
            for line in f:
                digest, relpath = line.rstrip("\n").split("  ", 1)
                expected[relpath] = digest
        current = {p.relative_to(root).as_posix(): file_hash(p) for p in files}
        if set(expected) != set(current):
            print("MISMATCH: file set changed")
            sys.exit(1)
        changed = [rel for rel in expected if expected[rel] != current[rel]]
        if changed:
            print(f"MISMATCH: {len(changed)} file(s) changed content")
            sys.exit(1)
        print(f"OK: all {len(expected)} files byte-identical to manifest.")
        return

    raise SystemExit(f"unknown mode: {mode}")


if __name__ == "__main__":
    main()
