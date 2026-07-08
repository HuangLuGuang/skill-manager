#!/usr/bin/env python3
"""Platform-neutral Agent Manager verifier for third-party skills."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any


DEFAULT_IGNORES = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
LOADABLE_STATUSES = {"APPROVED", "DEPLOYED"}
SIGNING_KEY_ENV = "AGENT_MANAGER_SIGNING_KEY"
_ENV_LOADED = False


class VerifierError(RuntimeError):
    pass


class ApiError(VerifierError):
    def __init__(self, status_code: int, detail: str, skill_status: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.skill_status = skill_status
        super().__init__(f"Agent Manager API 返回 {status_code}: {detail}")


def signing_key() -> str:
    global _ENV_LOADED
    if not _ENV_LOADED and not os.environ.get("ENV_LOADED"):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        _ENV_LOADED = True
    return os.environ.get(SIGNING_KEY_ENV, "").strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_zip_mojibake(value: str) -> str:
    try:
        return value.encode("cp437").decode("utf-8")
    except UnicodeError:
        return value


def iter_skill_files(skill_dir: str | Path, ignores: set[str] | None = None) -> list[Path]:
    root = Path(skill_dir).resolve()
    ignored = ignores or set()
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in ignored for part in rel_parts):
            continue
        files.append(path)
    return files


def fingerprint_skill_dir(skill_dir: str | Path, ignores: set[str] | None = None) -> dict[str, Any]:
    root = Path(skill_dir).resolve()
    files = []
    total_bytes = 0
    for path in iter_skill_files(root, ignores=ignores):
        rel = "/".join(normalize_zip_mojibake(part) for part in path.relative_to(root).parts)
        size = path.stat().st_size
        digest = file_sha256(path)
        total_bytes += size
        files.append({"path": rel, "size": size, "sha256": digest})

    root_hash = hashlib.sha256()
    for item in files:
        root_hash.update(item["path"].encode("utf-8"))
        root_hash.update(b"\x00")
        root_hash.update(str(item["size"]).encode("utf-8"))
        root_hash.update(b"\x00")
        root_hash.update(item["sha256"].encode("utf-8"))
        root_hash.update(b"\x00")
    return {
        "fingerprint": "sha256:" + root_hash.hexdigest(),
        "files": files,
        "total_bytes": total_bytes,
    }


def compute_skill_signature(skill_dir: str | Path, ignores: set[str] | None = None) -> str:
    root = Path(skill_dir).resolve()
    if not root.is_dir():
        raise VerifierError(f"不是目录: {root}")

    parts = []
    files = iter_skill_files(root, ignores=ignores or set())
    for path in files:
        rel = "/".join(normalize_zip_mojibake(part) for part in path.relative_to(root).parts)
        parts.append(f"{rel}:{file_sha256(path)}\n")

    content = "".join(parts).encode()
    key = signing_key()
    if key:
        return hmac.new(key.encode(), content, hashlib.sha256).hexdigest()
    return hashlib.sha256(content).hexdigest()


def create_skill_zip(skill_dir: str | Path, output_dir: str | Path, ignores: set[str] | None = None) -> tuple[Path, dict[str, Any]]:
    root = Path(skill_dir).resolve()
    if not root.is_dir():
        raise VerifierError(f"不是目录: {root}")
    if not (root / "SKILL.md").is_file():
        raise VerifierError(f"SKILL.md 不存在: {root}")

    ignored = ignores or DEFAULT_IGNORES
    manifest = fingerprint_skill_dir(root, ignores=ignored)
    zip_path = Path(output_dir) / f"{root.name}-{uuid.uuid4().hex}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in manifest["files"]:
            archive.write(root / item["path"], item["path"])
    return zip_path, manifest


def read_skill_name(skill_dir: str | Path) -> str | None:
    skill_md = Path(skill_dir).resolve() / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        with skill_md.open("r", encoding="utf-8", errors="replace") as handle:
            first = handle.readline().strip()
            if first != "---":
                return None
            for line in handle:
                text = line.strip()
                if text == "---":
                    return None
                if text.startswith("name:"):
                    return text.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        return None
    return None


def _json_request(method: str, url: str, token: str, payload: dict[str, Any] | None) -> urllib.request.Request:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    return request


def _multipart_request(url: str, token: str, fields: dict[str, str], file_path: Path, field_name: str = "file") -> urllib.request.Request:
    boundary = f"----agent-manager-{uuid.uuid4().hex}"
    body = bytearray()
    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.extend(str(value).encode())
        body.extend(b"\r\n")

    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode())
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    request = urllib.request.Request(url, data=bytes(body), method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    return request


def api_request(
    method: str,
    url: str,
    token: str,
    *,
    json_body: dict[str, Any] | None = None,
    fields: dict[str, str] | None = None,
    file_path: Path | None = None,
) -> dict[str, Any]:
    if fields is not None and file_path is not None:
        request = _multipart_request(url, token, fields, file_path)
    else:
        request = _json_request(method, url, token, json_body)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            if not isinstance(payload, dict):
                raise VerifierError("Agent Manager 返回了非预期的响应格式")
            return payload
    except urllib.error.HTTPError as exc:
        raw_detail = exc.read().decode("utf-8", errors="replace")
        detail = raw_detail
        try:
            parsed = json.loads(raw_detail)
            skill_status = str(parsed.get("status") or "") if isinstance(parsed, dict) else ""
            if isinstance(parsed, dict) and parsed.get("detail"):
                detail_raw = parsed["detail"]
                detail = detail_raw if isinstance(detail_raw, str) else str(detail_raw)
        except json.JSONDecodeError:
            skill_status = ""
        raise ApiError(exc.code, detail, skill_status or None) from exc
    except urllib.error.URLError as exc:
        raise VerifierError(f"无法连接 Agent Manager: {exc.reason}") from exc


def normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def resolve_server(args: argparse.Namespace) -> str:
    server = (
        args.server
        or os.environ.get("AGENT_MANAGER_VERIFIER_BASE_URL")
        or os.environ.get("AGENT_MANAGER_BASE_URL")
    )
    if not server:
        raise VerifierError("缺少 Agent Manager 地址，请设置 AGENT_MANAGER_VERIFIER_BASE_URL、旧版 AGENT_MANAGER_BASE_URL，或传入 --server")
    return normalize_base_url(server)


def resolve_token(args: argparse.Namespace) -> str:
    token = (
        args.token
        or os.environ.get("AGENT_MANAGER_VERIFIER_TOKEN")
        or os.environ.get("AGENT_MANAGER_API_TOKEN")
        or os.environ.get("AGENT_MANAGER_ACCESS_TOKEN")
    )
    if not token:
        raise VerifierError("缺少接入凭证，请设置 AGENT_MANAGER_VERIFIER_TOKEN、旧版 AGENT_MANAGER_API_TOKEN/AGENT_MANAGER_ACCESS_TOKEN，或传入 --token")
    return token


def command_submit(args: argparse.Namespace) -> int:
    server = resolve_server(args)
    token = resolve_token(args)
    ignores = set(DEFAULT_IGNORES)
    if args.ignore:
        ignores.update(part.strip() for part in args.ignore.split(",") if part.strip())

    with tempfile.TemporaryDirectory(prefix="agent-manager-skill-verifier-") as tmp_dir:
        zip_path, manifest = create_skill_zip(args.path, tmp_dir, ignores=ignores)
        fields = {
            "manifest": json.dumps(manifest, ensure_ascii=False),
            "use_behavioral": str(bool(args.behavioral)).lower(),
            "use_skillspector": str(bool(args.deep_scan)).lower(),
            "use_llm": str(bool(args.llm)).lower(),
            "use_sandbox": str(bool(args.sandbox)).lower(),
            "no_cache": str(bool(args.no_cache)).lower(),
            "scanner_version": "agent-manager-skill-verifier",
        }
        if args.host_id:
            fields["host_id"] = args.host_id
        payload = api_request(
            "POST",
            f"{server}/api/v1/scanner/imports",
            token,
            fields=fields,
            file_path=zip_path,
        )
    print(f"已提交扫描: {payload.get('name', '-')} skill_id={payload.get('skill_id', '-')}, status={payload.get('status', '-')}")
    if payload.get("detail_url"):
        print(f"详情: {server}{payload['detail_url']}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    server = resolve_server(args)
    token = resolve_token(args)
    payload = api_request("GET", f"{server}/api/v1/scanner/imports/{args.skill_id}", token)
    print(f"Skill: {payload.get('name', '-')} ({payload.get('skill_id', args.skill_id)})")
    print(f"状态: {payload.get('status', '-')}")
    print(f"风险: {payload.get('risk_level') or '-'}")
    return 0


def _block_guidance(reason: str, status: str | None = None) -> str:
    text = reason or ""
    text_lower = text.lower()
    if "未授权使用该 Skill" in text:
        return "Skill 已批准也需要绑定到当前智能体。请管理员在 Agent Manager 的“智能体管理”中把该 Skill 加入当前智能体的允许 Skills。"
    if "接入凭证缺少权限" in text:
        return "请管理员在“统一凭证中心”为当前 Agent 运行凭证授予所需 runtime 权限。"
    if "绑定的智能体不匹配" in text:
        return "请检查当前 AGENT_ID 是否和运行凭证绑定的智能体一致，或重新签发绑定正确智能体的凭证。"
    signature_failed = "signature" in text_lower and any(word in text_lower for word in ("mismatch", "failed", "tampering"))
    if signature_failed or "内容完整性校验失败" in text:
        return "本地 Skill 内容和平台批准版本不一致。请重新提交扫描审批，或使用平台批准后的同一份 Skill 内容。"
    if status and not _is_loadable_status(status):
        return "请联系管理员在 Agent Manager 中审批通过该 Skill 后再使用。"
    return "请联系管理员在 Agent Manager 中查看该 Skill、当前智能体绑定关系和运行凭证配置。"


def _is_loadable_status(status: str | None) -> bool:
    return status in LOADABLE_STATUSES


def _print_block(reason: str, status: str | None = None) -> None:
    status_text = f" status={status}" if status else ""
    print(f"阻断: {reason}{status_text}")
    print(f"不要调用该 Skill。{_block_guidance(reason, status)}")


def command_verify(args: argparse.Namespace) -> int:
    server = resolve_server(args)
    token = resolve_token(args)
    ignores = set(DEFAULT_IGNORES)
    if args.ignore:
        ignores.update(part.strip() for part in args.ignore.split(",") if part.strip())
    agent_id = (args.agent_id or os.environ.get("AGENT_ID") or "").strip()
    if not agent_id:
        raise VerifierError("缺少 Agent 身份，请设置 AGENT_ID")
    skill_name = read_skill_name(args.path)
    if not skill_name and not args.skill_id:
        raise VerifierError("无法识别 Skill 名称。请确认目录包含带 name 的 SKILL.md，或传入 --skill-id")
    signature = compute_skill_signature(args.path, ignores=ignores)
    body = {
        "local_signature": signature,
        "agent_id": agent_id,
    }
    if skill_name:
        body["skill_name"] = skill_name
    if args.skill_id:
        body["skill_id"] = args.skill_id

    verify_payload = api_request(
        "POST",
        f"{server}/api/v1/access/runtime/verify-skill-signature",
        token,
        json_body=body,
    )
    if not verify_payload.get("allowed"):
        _print_block(str(verify_payload.get("reason") or "内容完整性校验失败"), verify_payload.get("status"))
        return 1
    verified_name = str(verify_payload.get("skill_name") or skill_name or "").strip()
    if not verified_name:
        _print_block("平台未返回 Skill 名称，无法继续加载校验", verify_payload.get("status"))
        return 1
    if not _is_loadable_status(verify_payload.get("status")):
        _print_block("Skill 尚未审批通过", verify_payload.get("status"))
        return 1

    can_load_url = f"{server}/api/v1/access/runtime/can-load/{urllib.parse.quote(verified_name)}"
    can_load_url += f"?agent_id={urllib.parse.quote(agent_id)}"
    can_load_payload = api_request("GET", can_load_url, token)
    if not can_load_payload.get("allowed"):
        _print_block(str(can_load_payload.get("reason") or "状态不允许加载"), can_load_payload.get("status"))
        return 1
    if not _is_loadable_status(can_load_payload.get("status")):
        _print_block("Skill 尚未审批通过", can_load_payload.get("status"))
        return 1

    print(f"允许加载: {verified_name} status={can_load_payload.get('status', '-')}, risk={can_load_payload.get('risk_level') or '-'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent Manager third-party skill verifier")
    parser.add_argument("--server", default=None, help="Agent Manager base URL; default AGENT_MANAGER_VERIFIER_BASE_URL")
    parser.add_argument("--token", default=None, help="Access token; default AGENT_MANAGER_VERIFIER_TOKEN")
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit", help="Upload a local skill for Agent Manager scanning")
    submit.add_argument("--server", default=None, help="Agent Manager base URL; default AGENT_MANAGER_VERIFIER_BASE_URL")
    submit.add_argument("--token", default=None, help="Access token; default AGENT_MANAGER_VERIFIER_TOKEN")
    submit.add_argument("--path", required=True, help="Local skill directory")
    submit.add_argument("--behavioral", action="store_true", help="Enable server rule analysis")
    submit.add_argument("--deep-scan", action="store_true", help="Enable server deep scan")
    submit.add_argument("--sandbox", action="store_true", help="Enable sandbox analysis")
    submit.add_argument("--llm", action="store_true", help="Enable LLM analysis")
    submit.add_argument("--no-cache", action="store_true", help="Force server-side rescan without cache")
    submit.add_argument("--host-id", default=None, help="Optional host/environment identifier")
    submit.add_argument("--ignore", default="", help="Comma-separated extra ignored directories")
    submit.set_defaults(func=command_submit)

    status = subparsers.add_parser("status", help="Read scanner submission status")
    status.add_argument("--server", default=None, help="Agent Manager base URL; default AGENT_MANAGER_VERIFIER_BASE_URL")
    status.add_argument("--token", default=None, help="Access token; default AGENT_MANAGER_VERIFIER_TOKEN")
    status.add_argument("--skill-id", required=True, help="Submitted skill id")
    status.set_defaults(func=command_status)

    verify = subparsers.add_parser("verify", help="Verify local skill signature and load status")
    verify.add_argument("--server", default=None, help="Agent Manager base URL; default AGENT_MANAGER_VERIFIER_BASE_URL")
    verify.add_argument("--token", default=None, help="Access token; default AGENT_MANAGER_VERIFIER_TOKEN")
    verify.add_argument("--path", required=True, help="Local skill directory")
    verify.add_argument("--skill-id", default=None, help="Optional skill id to disambiguate same-name skills")
    verify.add_argument("--agent-id", default=None, help="Agent identifier; default AGENT_ID")
    verify.add_argument("--ignore", default="", help="Comma-separated extra ignored directories; defaults match submit")
    verify.set_defaults(func=command_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ApiError as exc:
        print(f"阻断: {exc}")
        print(f"不要调用该 Skill。{_block_guidance(exc.detail, exc.skill_status)}")
        return 1
    except VerifierError as exc:
        print(f"阻断: {exc}")
        print("不要调用该 Skill。请修正本地路径、环境变量或平台连接问题后重试。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
