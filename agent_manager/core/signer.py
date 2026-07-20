"""
Skill content signing and verification.

Computes a deterministic HMAC-SHA256 over the sorted file tree of a skill
directory. The signature is stored in the registry and re-verified at runtime
to detect tampering.

The signing key is read from the AGENT_MANAGER_SIGNING_KEY environment variable.
If unset, falls back to a plain SHA256 (no authentication — suitable for dev only).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SIGNING_KEY_ENV = "AGENT_MANAGER_SIGNING_KEY"
_DEV_WARNING_SHOWN = False

# Directories whose contents are excluded from signature computation.
# Must match the client-side DEFAULT_IGNORES in agent_manager_skill_verifier.py.
SKILL_IGNORE_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", "dist", "build"})

_ENV_LOADED = False


def _normalize_zip_mojibake(value: str) -> str:
    try:
        return value.encode("cp437").decode("utf-8")
    except UnicodeError:
        return value

def _get_key() -> bytes | None:
    # Lazily load dotenv if not already loaded to avoid import-time side effects
    global _ENV_LOADED
    if not _ENV_LOADED and not os.environ.get("ENV_LOADED"):
        try:
            from dotenv import load_dotenv
            load_dotenv()
            _ENV_LOADED = True
        except ImportError:
            pass

    key = os.environ.get(_SIGNING_KEY_ENV, "").strip()
    if not key:
        global _DEV_WARNING_SHOWN
        if not _DEV_WARNING_SHOWN:
            logger.warning(
                "AGENT_MANAGER_SIGNING_KEY not set — using unsigned SHA256. "
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


def _signature_content(skill_path: str | Path) -> bytes:
    root = Path(skill_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    files: list[tuple[str, Path]] = []
    for fpath in root.rglob("*"):
        if not fpath.is_file() or fpath.is_symlink():
            continue
        rel_parts = fpath.relative_to(root).parts
        if any(part in SKILL_IGNORE_DIRS for part in rel_parts):
            continue
        rel = "/".join(_normalize_zip_mojibake(part) for part in fpath.relative_to(root).parts)
        files.append((rel, fpath))

    parts: list[str] = []
    for rel, fpath in sorted(files, key=lambda item: item[0]):
        file_hash = _content_hash(fpath)
        parts.append(f"{rel}:{file_hash}\n")

    return "".join(parts).encode()


def compute_content_digest(skill_path: str | Path) -> str:
    """Compute the keyless content digest used to diagnose client HMAC setup."""
    return hashlib.sha256(_signature_content(skill_path)).hexdigest()


def compute_signature(skill_path: str | Path) -> str:
    """Compute the configured HMAC-SHA256, or plain SHA256 in dev mode."""
    content = _signature_content(skill_path)
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
        return hmac.compare_digest(actual, expected_signature)
    except Exception as e:
        logger.error("Signature verification failed for %s: %s", skill_path, e)
        return False


# --------------------------------------------------------------------------- #
# Prompt signing                                                               #
# --------------------------------------------------------------------------- #


def compute_prompt_signature(content: str) -> str:
    """Compute HMAC-SHA256 signature for a prompt text.

    If AGENT_MANAGER_SIGNING_KEY is set, uses HMAC-SHA256.
    Otherwise falls back to plain SHA256 (dev mode).
    """
    key = _get_key()
    data = content.encode("utf-8")
    if key:
        return hmac.new(key, data, hashlib.sha256).hexdigest()
    return hashlib.sha256(data).hexdigest()


def compute_prompt_file_signature(file_path: str | Path) -> str:
    """Compute signature for a prompt file on disk."""
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    return compute_prompt_signature(path.read_text(encoding="utf-8"))


def verify_prompt_signature(content_or_path: str | Path, expected_signature: str) -> bool:
    """Verify prompt content or file against the expected signature.

    If the argument is a Path or an existing file path string, reads the file.
    Otherwise treats it as raw prompt content.
    """
    try:
        path = Path(content_or_path)
        if path.is_file():
            actual = compute_prompt_file_signature(path)
        else:
            actual = compute_prompt_signature(str(content_or_path))
        return hmac.compare_digest(actual, expected_signature)
    except Exception as e:
        logger.error("Prompt signature verification failed: %s", e)
        return False
