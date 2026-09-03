#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

IGNORED_NAMES = {".DS_Store"}
IGNORED_PARTS = {".git", "__pycache__", "build"}
IGNORED_PART_SUFFIXES = (".egg-info",)
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def tree_sha256(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"vendored component is not a directory: {root}")
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(
            part in IGNORED_PARTS or part.endswith(IGNORED_PART_SUFFIXES)
            for part in relative.parts
        ):
            continue
        if path.is_symlink():
            raise ValueError(f"vendored component contains a symlink: {relative.as_posix()}")
        if path.is_file() and path.name not in IGNORED_NAMES and path.suffix not in IGNORED_SUFFIXES:
            files.append(path)
    if not files:
        raise ValueError(f"vendored component is empty: {root}")
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def verify(lock_path: Path, vendor_base: Path, components: set[str] | None = None) -> None:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    reuse = lock["integrations"]["ai_infra_guard"]["reuse"]
    checked = 0
    for item in reuse:
        component = str(item["component"])
        if components and component not in components:
            continue
        verification_subpath = str(item.get("verification_subpath") or component)
        actual = tree_sha256(vendor_base / verification_subpath)
        expected = str(item["vendored_tree_sha256"])
        if actual != expected:
            raise ValueError(
                f"vendored tree hash mismatch for {component}: expected {expected}, got {actual}"
            )
        checked += 1
    if checked == 0:
        raise ValueError("no matching vendored components were found in the upstream lock")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify deterministic hashes for vendored AI-Infra-Guard trees")
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--vendor-base", required=True, type=Path)
    parser.add_argument("--component", action="append", default=[])
    args = parser.parse_args()
    verify(args.lock, args.vendor_base, set(args.component) or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
