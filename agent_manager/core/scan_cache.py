"""Scan result cache keyed by skill content and scan context fingerprints."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import LLMConfig
from .models import RegistryEntry
from .policy import CompanyPolicy
from .sandbox import SandboxConfig
from .skillspector import get_skillspector_version

SCAN_CACHE_SCHEMA_VERSION = "1"


def compute_content_fingerprint(skill_path: str | Path) -> str:
    """Compute a deterministic, non-secret SHA256 fingerprint of a skill tree."""
    root = Path(skill_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        files.append({
            "path": rel,
            "size": path.stat().st_size,
            "sha256": digest.hexdigest(),
        })

    return "sha256:" + _stable_hash({"files": files})


def compute_scan_context_fingerprint(
    policy: CompanyPolicy,
    use_behavioral: bool,
    use_llm: bool,
    use_sandbox: bool,
) -> str:
    """Fingerprint scanner capabilities and selected scan options."""
    payload: dict[str, Any] = {
        "schema_version": SCAN_CACHE_SCHEMA_VERSION,
        "policy": policy.to_dict(),
        "scan_options": {
            "use_behavioral": use_behavioral,
            "use_llm": use_llm,
            "use_sandbox": use_sandbox,
        },
        "scanner": {
            "package_version": _distribution_version("cisco-ai-skill-scanner"),
            "vetting_py": _file_hash(Path(__file__).with_name("vetting.py")),
            "policy_py": _file_hash(Path(__file__).with_name("policy.py")),
        },
        "skillspector": {
            "enabled": policy.skillspector_enabled,
            "use_llm": getattr(policy, "skillspector_use_llm", False),
            "version": get_skillspector_version() if policy.skillspector_enabled else None,
            "timeout_seconds": policy.skillspector_timeout_seconds,
            "adapter_source": _file_hash(Path(__file__).with_name("skillspector.py")),
        },
        "rule_analysis": {
            "enabled": use_behavioral,
            "rule_source": _file_hash(Path(__file__).with_name("vetting.py")),
        },
    }
    if use_llm:
        payload["llm"] = _llm_context()
    if use_sandbox:
        payload["sandbox"] = _sandbox_context()
    return "sha256:" + _stable_hash(payload)


def compute_scan_cache_key(content_fingerprint: str, scan_context_fingerprint: str) -> str:
    return "sha256:" + _stable_hash({
        "content_fingerprint": content_fingerprint,
        "scan_context_fingerprint": scan_context_fingerprint,
    })


class ScanCacheStore:
    def __init__(self, data_dir: str | Path):
        self.cache_dir = Path(data_dir) / "scan_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.cache_dir / "index.json"

    def get(self, cache_key: str) -> dict[str, Any] | None:
        return self._load().get(cache_key)

    def put(
        self,
        cache_key: str,
        entry: RegistryEntry,
        content_fingerprint: str,
        scan_context_fingerprint: str,
    ) -> None:
        if entry.vetting is None or entry.status.value == "PENDING":
            return
        index = self._load()
        index[cache_key] = {
            "skill_id": entry.skill_id,
            "skill_name": entry.name,
            "status": entry.status.value,
            "risk_level": entry.risk_level.value if entry.risk_level else None,
            "content_fingerprint": content_fingerprint,
            "scan_context_fingerprint": scan_context_fingerprint,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save(index)

    def _load(self) -> dict[str, Any]:
        if not self.index_file.exists():
            return {}
        try:
            return json.loads(self.index_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, index: dict[str, Any]) -> None:
        self.index_file.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _llm_context() -> dict[str, Any]:
    try:
        cfg = LLMConfig.load()
        return {
            "enabled": cfg.enabled,
            "provider": cfg.provider,
            "api_base": cfg.api_base,
            "model": cfg.model,
            "timeout_seconds": cfg.timeout_seconds,
            "max_files": cfg.max_files,
            "max_file_chars": cfg.max_file_chars,
            "max_manifest_chars": cfg.max_manifest_chars,
            "prompt_source": _file_hash(Path(__file__).with_name("llm.py")),
        }
    except Exception as exc:
        return {"error": str(exc), "prompt_source": _file_hash(Path(__file__).with_name("llm.py"))}


def _sandbox_context() -> dict[str, Any]:
    try:
        cfg = SandboxConfig.load()
        return {
            "enabled": cfg.enabled,
            "runtime": cfg.runtime,
            "image": cfg.image,
            "timeout_seconds": cfg.timeout_seconds,
            "network_mode": cfg.network_mode,
            "memory_limit": cfg.memory_limit,
            "cpu_limit": cfg.cpu_limit,
            "pids_limit": cfg.pids_limit,
            "read_only_rootfs": cfg.read_only_rootfs,
            "remote_url": cfg.remote_url,
            "runner_source": _file_hash(Path(__file__).with_name("sandbox.py")),
        }
    except Exception as exc:
        return {"error": str(exc), "runner_source": _file_hash(Path(__file__).with_name("sandbox.py"))}
