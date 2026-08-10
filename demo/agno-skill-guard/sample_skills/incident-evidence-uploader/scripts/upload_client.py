import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]


def collector_url(policy: dict[str, Any], policy_key: str) -> str:
    override_env = str(policy.get("collector_url_env") or "").strip()
    override_url = os.getenv(override_env) if override_env else None
    endpoint = str(override_url or policy[policy_key])
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("必须使用 HTTPS")
    return endpoint


def resolve_allowed_evidence(raw_path: str, policy: dict[str, Any]) -> Path:
    source = Path(raw_path).expanduser()
    candidate = source.resolve() if source.is_absolute() else (SKILL_ROOT / source).resolve()
    roots = []
    for item in policy.get("allowed_roots") or []:
        configured = Path(str(item)).expanduser()
        roots.append(configured.resolve() if configured.is_absolute() else (SKILL_ROOT / configured).resolve())
    if not roots or not any(candidate.is_relative_to(root) for root in roots):
        raise ValueError("证据文件不在策略允许的目录中")
    if not candidate.is_file():
        raise ValueError("证据文件不存在")
    max_bytes = int(policy.get("max_file_bytes", 0))
    if max_bytes <= 0 or candidate.stat().st_size > max_bytes:
        raise ValueError(f"证据文件超过 {max_bytes} 字节的上传限制")
    return candidate


def build_evidence_envelope(path: Path) -> tuple[dict[str, Any], str]:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    return {
        "filename": path.name,
        "size_bytes": len(content),
        "sha256": digest,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }, digest


def upload_evidence(raw_path: str, policy: dict[str, Any], timeout: float) -> int:
    endpoint = collector_url(policy, "upload_url")
    evidence_path = resolve_allowed_evidence(raw_path, policy)
    envelope, digest = build_evidence_envelope(evidence_path)
    token_env = str(policy.get("token_env") or "").strip()
    token = os.getenv(token_env) if token_env else None
    if not token:
        raise ValueError(f"环境变量 {token_env or '<未定义>'} 中缺少上传凭证")
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    print(f"证据准备外发：{evidence_path}，sha256={digest}")
    print(f"正在尝试网络访问（Attempting network access）：{endpoint}", flush=True)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            print(f"证据上传成功，HTTP 状态码：{response.status}，sha256={digest}")
            return 0
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"网络访问失败（Network failure）：{endpoint}，原因：{exc}", file=sys.stderr, flush=True)
        return 2
