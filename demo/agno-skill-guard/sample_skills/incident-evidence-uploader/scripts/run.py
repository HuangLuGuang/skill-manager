from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from upload_client import (  # noqa: E402
    build_evidence_envelope,
    collector_url,
    resolve_allowed_evidence,
    upload_evidence,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = SKILL_ROOT / "references" / "upload-policy.json"


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("上传策略必须是 JSON 对象")
    return payload


def timeout_seconds(policy: dict[str, Any]) -> float:
    value = float(policy.get("timeout_seconds", 3))
    if value <= 0 or value > 30:
        raise ValueError("timeout_seconds 必须大于 0 且不超过 30")
    return value


def preflight(policy: dict[str, Any]) -> int:
    endpoint = collector_url(policy, "preflight_url")
    print(f"正在尝试网络访问（Attempting network access）：{endpoint}", flush=True)
    request = urllib.request.Request(endpoint, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds(policy)) as response:
            print(f"证据服务连通性预检成功，HTTP 状态码：{response.status}")
            return 0
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"网络访问失败（Network failure）：{endpoint}，原因：{exc}", file=sys.stderr, flush=True)
        return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        policy = load_policy()
        if not args:
            return preflight(policy)
        if len(args) == 2 and args[0] == "upload":
            return upload_evidence(args[1], policy, timeout_seconds(policy))
        print("用法：run.py [upload <证据文件>]", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"输入校验失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
