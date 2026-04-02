"""
Skill content signing and verification.

Computes a deterministic HMAC-SHA256 over the sorted file tree of a skill
directory. The signature is stored in the registry and re-verified at runtime
to detect tampering.

The signing key is read from the SKILL_MANAGER_SIGNING_KEY environment variable.
If unset, falls back to a plain SHA256 (no authentication — suitable for dev only).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_SIGNING_KEY_ENV = "SKILL_MANAGER_SIGNING_KEY"
_DEV_WARNING_SHOWN = False


def _get_key() -> bytes | None:
    key = os.environ.get(_SIGNING_KEY_ENV, "").strip()
    if not key:
        global _DEV_WARNING_SHOWN
        if not _DEV_WARNING_SHOWN:
            logger.warning(
                "SKILL_MANAGER_SIGNING_KEY not set — using unsigned SHA256. "
                "Set this env var in production."
            )
            _DEV_WARNING_SHOWN = True
        return None
    return key.encode()


def _content_hash(path: Path) -> str:
    """SHA256 of a single file's content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_signature(skill_path: str | Path) -> str:
    """
    Compute a stable signature for a skill directory.

    Walks all files sorted by relative path, hashes each file's content,
    then produces a final HMAC-SHA256 (or SHA256 in dev mode) over the
    concatenated 'relpath:filehash\\n' lines.
    """
    root = Path(skill_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    parts: list[str] = []
    for fpath in sorted(root.rglob("*")):
        if fpath.is_file():
            rel = fpath.relative_to(root).as_posix()
            file_hash = _content_hash(fpath)
            parts.append(f"{rel}:{file_hash}\n")

    content = "".join(parts).encode()
    key = _get_key()

    if key:
        sig = hmac.new(key, content, hashlib.sha256).hexdigest()
    else:
        sig = hashlib.sha256(content).hexdigest()

    return sig


def verify_signature(skill_path: str | Path, expected_signature: str) -> bool:
    """
    Verify that a skill directory matches its registered signature.

    Returns True if signature matches, False otherwise.
    """
    try:
        actual = compute_signature(skill_path)
        # Use hmac.compare_digest to prevent timing attacks
        return hmac.compare_digest(actual, expected_signature)
    except Exception as e:
        logger.error("Signature verification failed for %s: %s", skill_path, e)
        return False
