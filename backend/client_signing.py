import base64
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .config import settings
from agent_manager.core.signer import SKILL_IGNORE_DIRS



def _key_path() -> Path:
    return Path(settings.DATA_DIR) / "client_release_ed25519.pem"


@lru_cache(maxsize=1)
def private_key() -> Ed25519PrivateKey:
    path = _key_path()
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    body = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    try:
        with path.open("xb") as handle:
            handle.write(body)
    except FileExistsError:
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.chmod(0o600)
    return key


def public_key_base64() -> str:
    raw = private_key().public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def build_manifest(skill_id: str, name: str, skill_root: Path, content_signature: str | None) -> dict:
    files = []
    for path in sorted(skill_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(skill_root)
        if any(part in SKILL_IGNORE_DIRS for part in rel.parts):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append({"path": rel.as_posix(), "size": path.stat().st_size, "sha256": digest.hexdigest()})
    return {
        "version": 1,
        "skill_id": skill_id,
        "name": name,
        "content_signature": content_signature,
        "files": files,
    }


def compute_content_signature(skill_root: Path) -> str:
    root = skill_root.resolve()
    return _cached_content_signature(str(root), _tree_version(root))


def _tree_version(skill_root: Path) -> tuple:
    items = []
    for path in sorted(skill_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(skill_root)
        if any(part in SKILL_IGNORE_DIRS for part in rel.parts):
            continue
        stat = path.stat()
        items.append((rel.as_posix(), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(items)


@lru_cache(maxsize=256)
def _cached_content_signature(skill_root: str, tree_version: tuple) -> str:
    manifest = build_manifest("", "", Path(skill_root), None)
    content = "".join(f"{item['path']}:{item['sha256']}\n" for item in manifest["files"]).encode()
    return hashlib.sha256(content).hexdigest()


def canonical_manifest(manifest: dict) -> bytes:
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict) -> str:
    return base64.b64encode(private_key().sign(canonical_manifest(manifest))).decode("ascii")
