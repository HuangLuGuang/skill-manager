"""Skill and Prompt signing with an Ed25519 server identity.

New approvals use an authenticated signature envelope:

    ed25519:v1:<key-id>:<content-digest>:<base64-signature>

Agents never need the private key. They calculate the keyless SHA256 content
digest for online verification, or verify the envelope with the exported public
key for offline verification.

Legacy 64-character HMAC/SHA256 records remain verifiable when their old
configuration is still present, but this module never creates new legacy
signatures.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


logger = logging.getLogger(__name__)

_LEGACY_SIGNING_KEY_ENV = "AGENT_MANAGER_SIGNING_KEY"
_PRIVATE_KEY_PATH_ENV = "AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH"
_PUBLIC_KEY_PATH_ENV = "AGENT_MANAGER_SIGNING_PUBLIC_KEY_PATH"
_PUBLIC_KEY_ENV = "AGENT_MANAGER_SIGNING_PUBLIC_KEY"
_ENVELOPE_PREFIX = "ed25519:v1"
_KEY_ID_PATTERN = re.compile(r"[0-9a-f]{16}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_ED25519_SIGNATURE_BYTES = 64

# Must match client-side ignore sets.
SKILL_IGNORE_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", "dist", "build", ".DS_Store"})


def normalize_zip_mojibake(value: str) -> str:
    try:
        return value.encode("cp437").decode("utf-8")
    except UnicodeError:
        return value


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _signature_content(skill_path: str | Path) -> bytes:
    root = Path(skill_path)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    files: list[tuple[str, Path]] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file() or file_path.is_symlink():
            continue
        relative_parts = file_path.relative_to(root).parts
        if any(part in SKILL_IGNORE_DIRS for part in relative_parts):
            continue
        relative = "/".join(normalize_zip_mojibake(part) for part in relative_parts)
        files.append((relative, file_path))

    lines = [
        f"{relative}:{_content_hash(file_path)}\n"
        for relative, file_path in sorted(files, key=lambda item: item[0])
    ]
    return "".join(lines).encode()


def compute_content_digest(skill_path: str | Path) -> str:
    """Return the keyless digest an Agent submits to the Runtime API."""
    return hashlib.sha256(_signature_content(skill_path)).hexdigest()


def compute_prompt_content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _default_private_key_path() -> Path:
    data_dir = Path(os.environ.get("AGENT_MANAGER_DATA_DIR", Path.home() / ".agent-manager"))
    return data_dir.expanduser().resolve() / "signing" / "skill-ed25519.pem"


def _private_key_path() -> Path:
    configured = os.environ.get(_PRIVATE_KEY_PATH_ENV, "").strip()
    return Path(configured).expanduser().resolve() if configured else _default_private_key_path()


def _load_or_create_private_key() -> Ed25519PrivateKey:
    path = _private_key_path()
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError(f"Signing key is not Ed25519: {path}")
        return key

    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    encoded = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
        path.chmod(0o600)
        return key
    except FileExistsError:
        loaded = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise RuntimeError(f"Signing key is not Ed25519: {path}")
        return loaded


def _load_private_key() -> Ed25519PrivateKey:
    path = _private_key_path()
    if not path.exists():
        raise RuntimeError(f"Signing private key is not initialized: {path}")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError(f"Signing key is not Ed25519: {path}")
    return key


def ensure_signing_key() -> Path:
    _load_or_create_private_key()
    return _private_key_path()


def validate_signing_key() -> Path:
    """Load an existing Ed25519 private key without creating filesystem state."""
    _load_private_key()
    return _private_key_path()


def _load_public_key() -> Ed25519PublicKey:
    inline = os.environ.get(_PUBLIC_KEY_ENV, "").strip()
    if inline:
        raw = base64.b64decode(inline, validate=True)
        return Ed25519PublicKey.from_public_bytes(raw)

    configured_path = os.environ.get(_PUBLIC_KEY_PATH_ENV, "").strip()
    if configured_path:
        path = Path(configured_path).expanduser().resolve()
        body = path.read_bytes()
        try:
            loaded = serialization.load_pem_public_key(body)
            if not isinstance(loaded, Ed25519PublicKey):
                raise RuntimeError(f"Signing public key is not Ed25519: {path}")
            return loaded
        except ValueError:
            return Ed25519PublicKey.from_public_bytes(base64.b64decode(body.strip(), validate=True))

    return _load_private_key().public_key()


def signing_public_key_base64() -> str:
    raw = _load_public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def signing_key_id() -> str:
    return _key_id(_load_public_key())


def _key_id(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()[:16]


def _message(kind: str, digest: str) -> bytes:
    return f"agent-manager:{kind}:v1:{digest}".encode("ascii")


def _sign_digest(kind: str, digest: str) -> str:
    private_key = _load_or_create_private_key()
    signature = base64.b64encode(private_key.sign(_message(kind, digest))).decode("ascii")
    return f"{_ENVELOPE_PREFIX}:{_key_id(private_key.public_key())}:{digest}:{signature}"


def _decode_envelope(value: str) -> tuple[str, str, bytes] | None:
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 5 or parts[0] != "ed25519" or parts[1] != "v1":
        return None
    key_id, digest, encoded_signature = parts[2], parts[3], parts[4]
    if not _KEY_ID_PATTERN.fullmatch(key_id) or not _DIGEST_PATTERN.fullmatch(digest):
        return None
    try:
        signature = base64.b64decode(encoded_signature, validate=True)
    except Exception:
        return None
    if len(signature) != _ED25519_SIGNATURE_BYTES:
        return None
    return key_id, digest, signature


def signature_content_digest(signature: str | None) -> str | None:
    decoded = _decode_envelope(signature or "")
    return decoded[1] if decoded else None


def _verify_envelope(kind: str, expected_digest: str, envelope: str) -> bool:
    decoded = _decode_envelope(envelope)
    if (
        not decoded
        or not isinstance(expected_digest, str)
        or not _DIGEST_PATTERN.fullmatch(expected_digest)
    ):
        return False
    key_id, signed_digest, signature = decoded
    if not hmac.compare_digest(signed_digest, expected_digest):
        return False
    try:
        public_key = _load_public_key()
        if not hmac.compare_digest(key_id, _key_id(public_key)):
            return False
        public_key.verify(signature, _message(kind, signed_digest))
        return True
    except Exception:
        return False


def _legacy_signature(content: bytes) -> str:
    key = os.environ.get(_LEGACY_SIGNING_KEY_ENV, "").strip()
    if key:
        return hmac.new(key.encode(), content, hashlib.sha256).hexdigest()
    return hashlib.sha256(content).hexdigest()


def compute_signature(skill_path: str | Path) -> str:
    """Create a server-authenticated Ed25519 signature envelope."""
    return _sign_digest("skill", compute_content_digest(skill_path))


def verify_signature(skill_path: str | Path, expected_signature: str) -> bool:
    try:
        digest = compute_content_digest(skill_path)
        if _decode_envelope(expected_signature):
            return _verify_envelope("skill", digest, expected_signature)
        return hmac.compare_digest(_legacy_signature(_signature_content(skill_path)), expected_signature)
    except Exception as exc:
        logger.error("Signature verification failed for %s: %s", skill_path, exc)
        return False


def compute_prompt_signature(content: str) -> str:
    return _sign_digest("prompt", compute_prompt_content_digest(content))


def compute_prompt_file_signature(file_path: str | Path) -> str:
    path = Path(file_path)
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    return compute_prompt_signature(path.read_text(encoding="utf-8"))


def verify_prompt_signature(content_or_path: str | Path, expected_signature: str) -> bool:
    try:
        path = Path(content_or_path)
        content = path.read_text(encoding="utf-8") if path.is_file() else str(content_or_path)
        digest = compute_prompt_content_digest(content)
        if _decode_envelope(expected_signature):
            return _verify_envelope("prompt", digest, expected_signature)
        return hmac.compare_digest(
            _legacy_signature(content.encode("utf-8")),
            expected_signature,
        )
    except Exception as exc:
        logger.error("Prompt signature verification failed: %s", exc)
        return False
