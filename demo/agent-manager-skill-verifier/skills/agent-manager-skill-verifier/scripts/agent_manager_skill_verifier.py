#!/usr/bin/env python3
"""Platform-neutral Agent Manager verifier for third-party skills."""

from __future__ import annotations

import argparse
import hashlib
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


DEFAULT_IGNORES = {".git", ".venv", "node_modules", "__pycache__", "dist", "build", ".DS_Store"}
LOADABLE_STATUSES = {"APPROVED", "DEPLOYED"}


class VerifierError(RuntimeError):
    pass


class ApiError(VerifierError):
    def __init__(
        self,
        status_code: int,
        detail: str,
        skill_status: str | None = None,
        error_code: str | None = None,
    ):
        self.status_code = status_code
        self.detail = detail
        self.skill_status = skill_status
        self.error_code = error_code
        super().__init__(
            ui_text(
                f"Agent Manager API 返回 {status_code}: {detail}",
                f"Agent Manager API returned {status_code}: {detail}",
            )
        )


def request_locale() -> str:
    value = os.environ.get("AGENT_MANAGER_VERIFIER_LANG") or os.environ.get("LANG") or ""
    return "en-US" if value.strip().lower().startswith("en") else "zh-CN"


def ui_text(zh: str, en: str) -> str:
    return en if request_locale() == "en-US" else zh


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
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in ignored for part in rel_parts):
            continue
        files.append(path)
    return sorted(
        files,
        key=lambda path: "/".join(
            normalize_zip_mojibake(part) for part in path.relative_to(root).parts
        ),
    )


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
        raise VerifierError(ui_text(f"不是目录: {root}", f"Not a directory: {root}"))

    parts = []
    files = iter_skill_files(root, ignores=ignores or set())
    for path in files:
        rel = "/".join(normalize_zip_mojibake(part) for part in path.relative_to(root).parts)
        parts.append(f"{rel}:{file_sha256(path)}\n")

    content = "".join(parts).encode()
    return hashlib.sha256(content).hexdigest()


def create_skill_zip(skill_dir: str | Path, output_dir: str | Path, ignores: set[str] | None = None) -> tuple[Path, dict[str, Any]]:
    root = Path(skill_dir).resolve()
    if not root.is_dir():
        raise VerifierError(ui_text(f"不是目录: {root}", f"Not a directory: {root}"))
    if not (root / "SKILL.md").is_file():
        raise VerifierError(ui_text(f"SKILL.md 不存在: {root}", f"SKILL.md not found: {root}"))

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
    request.add_header("Accept-Language", request_locale())
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
    request.add_header("Accept-Language", request_locale())
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
                raise VerifierError(
                    ui_text(
                        "Agent Manager 返回了非预期的响应格式",
                        "Agent Manager returned an unexpected response format",
                    )
                )
            return payload
    except urllib.error.HTTPError as exc:
        raw_detail = exc.read().decode("utf-8", errors="replace")
        detail = raw_detail
        try:
            parsed = json.loads(raw_detail)
            skill_status = str(parsed.get("status") or "") if isinstance(parsed, dict) else ""
            error_code = str(parsed.get("error_code") or "") if isinstance(parsed, dict) else ""
            if isinstance(parsed, dict) and parsed.get("detail"):
                detail_raw = parsed["detail"]
                detail = detail_raw if isinstance(detail_raw, str) else str(detail_raw)
        except json.JSONDecodeError:
            skill_status = ""
            error_code = ""
        raise ApiError(exc.code, detail, skill_status or None, error_code or None) from exc
    except urllib.error.URLError as exc:
        raise VerifierError(
            ui_text(
                f"无法连接 Agent Manager: {exc.reason}",
                f"Could not connect to Agent Manager: {exc.reason}",
            )
        ) from exc


def normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def resolve_server(args: argparse.Namespace) -> str:
    server = (
        args.server
        or os.environ.get("AGENT_MANAGER_VERIFIER_BASE_URL")
        or os.environ.get("AGENT_MANAGER_BASE_URL")
    )
    if not server:
        raise VerifierError(
            ui_text(
                "缺少 Agent Manager 地址，请设置 AGENT_MANAGER_VERIFIER_BASE_URL、旧版 AGENT_MANAGER_BASE_URL，或传入 --server",
                "Missing Agent Manager URL. Set AGENT_MANAGER_VERIFIER_BASE_URL, the legacy AGENT_MANAGER_BASE_URL, or pass --server.",
            )
        )
    return normalize_base_url(server)


def resolve_token(args: argparse.Namespace, *, purpose: str = "runtime") -> str:
    preferred_env = "AGENT_MANAGER_SCANNER_TOKEN" if purpose == "scanner" else "AGENT_MANAGER_AGENT_RUNTIME_TOKEN"
    token = (
        args.token
        or os.environ.get(preferred_env)
        or os.environ.get("AGENT_MANAGER_VERIFIER_TOKEN")
        or os.environ.get("AGENT_MANAGER_API_TOKEN")
        or os.environ.get("AGENT_MANAGER_ACCESS_TOKEN")
    )
    if not token:
        raise VerifierError(
            ui_text(
                f"缺少接入凭证，请设置 {preferred_env}，或传入 --token",
                f"Missing access credential. Set {preferred_env}, or pass --token.",
            )
        )
    return token


def command_submit(args: argparse.Namespace) -> int:
    server = resolve_server(args)
    token = resolve_token(args, purpose="scanner")
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
    print(
        ui_text("已提交扫描", "Scan submitted")
        + f": {payload.get('name', '-')} skill_id={payload.get('skill_id', '-')}, status={payload.get('status', '-')}"
    )
    if payload.get("detail_url"):
        print(f"{ui_text('详情', 'Details')}: {server}{payload['detail_url']}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    server = resolve_server(args)
    token = resolve_token(args, purpose="scanner")
    payload = api_request("GET", f"{server}/api/v1/scanner/imports/{args.skill_id}", token)
    print(f"Skill: {payload.get('name', '-')} ({payload.get('skill_id', args.skill_id)})")
    print(f"{ui_text('状态', 'Status')}: {payload.get('status', '-')}")
    print(f"{ui_text('风险', 'Risk')}: {payload.get('risk_level') or '-'}")
    return 0


def _block_guidance(reason: str, status: str | None = None, error_code: str | None = None) -> str:
    text = reason or ""
    text_lower = text.lower()
    if error_code == "agent.skill_not_allowed" or "未授权使用该 Skill" in text:
        return ui_text(
            "Skill 已批准也需要绑定到当前智能体。请管理员在 Agent Manager 的“智能体管理”中把该 Skill 加入当前智能体的允许 Skills。",
            "An approved Skill must also be assigned to this Agent. Ask an administrator to add it to the Agent's allowed Skills in Agent Manager.",
        )
    if error_code == "credential.scope_missing" or "接入凭证缺少权限" in text:
        return ui_text(
            "请管理员在“统一凭证中心”为当前 Agent 运行凭证授予所需 runtime 权限。",
            "Ask an administrator to grant the required runtime scopes to this Agent credential in the Credential Center.",
        )
    if error_code == "agent.credential_binding_mismatch" or "绑定的智能体不匹配" in text:
        return ui_text(
            "请检查当前 AGENT_ID 是否和运行凭证绑定的智能体一致，或重新签发绑定正确智能体的凭证。",
            "Check that AGENT_ID matches the Agent bound to the credential, or issue a credential bound to the correct Agent.",
        )
    signature_failed = "signature" in text_lower and any(word in text_lower for word in ("mismatch", "failed", "tampering"))
    if signature_failed or "内容完整性校验失败" in text:
        return ui_text(
            "本地 Skill 内容和平台批准版本不一致。请重新提交扫描审批，或使用平台批准后的同一份 Skill 内容。",
            "The local Skill differs from the approved platform version. Resubmit it for scanning and approval, or use the exact approved content.",
        )
    if status and not _is_loadable_status(status):
        return ui_text(
            "请联系管理员在 Agent Manager 中审批通过该 Skill 后再使用。",
            "Ask an administrator to approve the Skill in Agent Manager before using it.",
        )
    return ui_text(
        "请联系管理员在 Agent Manager 中查看该 Skill、当前智能体绑定关系和运行凭证配置。",
        "Ask an administrator to review the Skill, Agent assignment, and runtime credential in Agent Manager.",
    )


def _is_loadable_status(status: str | None) -> bool:
    return status in LOADABLE_STATUSES


def _print_block(reason: str, status: str | None = None) -> None:
    status_text = f" status={status}" if status else ""
    print(f"{ui_text('阻断', 'Blocked')}: {reason}{status_text}")
    print(f"{ui_text('不要调用该 Skill。', 'Do not use this Skill. ')}{_block_guidance(reason, status)}")


def command_verify(args: argparse.Namespace) -> int:
    server = resolve_server(args)
    token = resolve_token(args, purpose="runtime")
    ignores = set(DEFAULT_IGNORES)
    if args.ignore:
        ignores.update(part.strip() for part in args.ignore.split(",") if part.strip())
    agent_id = (args.agent_id or os.environ.get("AGENT_ID") or "").strip()
    if not agent_id:
        raise VerifierError(ui_text("缺少 Agent 身份，请设置 AGENT_ID", "Missing Agent identity. Set AGENT_ID."))
    skill_name = read_skill_name(args.path)
    if not skill_name and not args.skill_id:
        raise VerifierError(
            ui_text(
                "无法识别 Skill 名称。请确认目录包含带 name 的 SKILL.md，或传入 --skill-id",
                "Could not identify the Skill name. Ensure SKILL.md contains name metadata, or pass --skill-id.",
            )
        )
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
        _print_block(
            str(
                verify_payload.get("reason")
                or ui_text("内容完整性校验失败", "Content integrity verification failed")
            ),
            verify_payload.get("status"),
        )
        return 1
    verified_name = str(verify_payload.get("skill_name") or skill_name or "").strip()
    if not verified_name:
        _print_block(
            ui_text(
                "平台未返回 Skill 名称，无法继续加载校验",
                "The platform did not return a Skill name, so load verification cannot continue",
            ),
            verify_payload.get("status"),
        )
        return 1
    if not _is_loadable_status(verify_payload.get("status")):
        _print_block(
            ui_text("Skill 尚未审批通过", "The Skill has not been approved"),
            verify_payload.get("status"),
        )
        return 1

    can_load_url = f"{server}/api/v1/access/runtime/can-load/{urllib.parse.quote(verified_name)}"
    can_load_url += f"?agent_id={urllib.parse.quote(agent_id)}"
    can_load_payload = api_request("GET", can_load_url, token)
    if not can_load_payload.get("allowed"):
        _print_block(
            str(
                can_load_payload.get("reason")
                or ui_text("状态不允许加载", "The current status does not allow loading")
            ),
            can_load_payload.get("status"),
        )
        return 1
    if not _is_loadable_status(can_load_payload.get("status")):
        _print_block(
            ui_text("Skill 尚未审批通过", "The Skill has not been approved"),
            can_load_payload.get("status"),
        )
        return 1

    print(
        f"{ui_text('允许加载', 'Allowed')}: {verified_name} "
        f"status={can_load_payload.get('status', '-')}, risk={can_load_payload.get('risk_level') or '-'}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=ui_text(
            "Agent Manager 第三方 Skill 验证器",
            "Agent Manager third-party Skill verifier",
        )
    )
    parser.add_argument(
        "--server",
        default=None,
        help=ui_text(
            "Agent Manager 地址；默认读取 AGENT_MANAGER_VERIFIER_BASE_URL",
            "Agent Manager base URL; defaults to AGENT_MANAGER_VERIFIER_BASE_URL",
        ),
    )
    parser.add_argument(
        "--token",
        default=None,
        help=ui_text(
            "接入凭证；默认读取 AGENT_MANAGER_VERIFIER_TOKEN",
            "Access credential; defaults to AGENT_MANAGER_VERIFIER_TOKEN",
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser(
        "submit",
        help=ui_text(
            "上传本地 Skill 到 Agent Manager 检测",
            "Upload a local Skill for Agent Manager scanning",
        ),
    )
    submit.add_argument("--server", default=None, help=ui_text("Agent Manager 地址", "Agent Manager base URL"))
    submit.add_argument("--token", default=None, help=ui_text("接入凭证", "Access credential"))
    submit.add_argument("--path", required=True, help=ui_text("本地 Skill 目录", "Local Skill directory"))
    submit.add_argument("--behavioral", action="store_true", help=ui_text("启用规则分析", "Enable server rule analysis"))
    submit.add_argument("--deep-scan", action="store_true", help=ui_text("启用深度扫描", "Enable server deep scan"))
    submit.add_argument("--sandbox", action="store_true", help=ui_text("启用 Sandbox 分析", "Enable Sandbox analysis"))
    submit.add_argument("--llm", action="store_true", help=ui_text("启用 LLM 分析", "Enable LLM analysis"))
    submit.add_argument("--no-cache", action="store_true", help=ui_text("禁用缓存并重新检测", "Force server-side rescan without cache"))
    submit.add_argument("--host-id", default=None, help=ui_text("可选的主机或环境标识", "Optional host or environment identifier"))
    submit.add_argument("--ignore", default="", help=ui_text("逗号分隔的额外忽略目录", "Comma-separated extra ignored directories"))
    submit.set_defaults(func=command_submit)

    status = subparsers.add_parser(
        "status",
        help=ui_text("查询检测提交状态", "Read scanner submission status"),
    )
    status.add_argument("--server", default=None, help=ui_text("Agent Manager 地址", "Agent Manager base URL"))
    status.add_argument("--token", default=None, help=ui_text("接入凭证", "Access credential"))
    status.add_argument("--skill-id", required=True, help=ui_text("已提交的 Skill ID", "Submitted Skill ID"))
    status.set_defaults(func=command_status)

    verify = subparsers.add_parser(
        "verify",
        help=ui_text(
            "校验本地 Skill 签名和加载状态",
            "Verify a local Skill signature and load status",
        ),
    )
    verify.add_argument("--server", default=None, help=ui_text("Agent Manager 地址", "Agent Manager base URL"))
    verify.add_argument("--token", default=None, help=ui_text("接入凭证", "Access credential"))
    verify.add_argument("--path", required=True, help=ui_text("本地 Skill 目录", "Local Skill directory"))
    verify.add_argument("--skill-id", default=None, help=ui_text("用于区分同名 Skill 的可选 ID", "Optional Skill ID for disambiguating duplicate names"))
    verify.add_argument("--agent-id", default=None, help=ui_text("Agent 标识；默认读取 AGENT_ID", "Agent identifier; defaults to AGENT_ID"))
    verify.add_argument("--ignore", default="", help=ui_text("逗号分隔的额外忽略目录", "Comma-separated extra ignored directories"))
    verify.set_defaults(func=command_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ApiError as exc:
        print(f"{ui_text('阻断', 'Blocked')}: {exc}")
        print(
            f"{ui_text('不要调用该 Skill。', 'Do not use this Skill. ')}"
            f"{_block_guidance(exc.detail, exc.skill_status, exc.error_code)}"
        )
        return 1
    except VerifierError as exc:
        print(f"{ui_text('阻断', 'Blocked')}: {exc}")
        print(
            ui_text(
                "不要调用该 Skill。请修正本地路径、环境变量或平台连接问题后重试。",
                "Do not use this Skill. Fix the local path, environment variables, or platform connection, then retry.",
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
