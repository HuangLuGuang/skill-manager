#!/usr/bin/env python3
"""Fail-closed Agent Manager guard for Codex PreToolUse hooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build", ".DS_Store"}
LOADABLE_STATUSES = {"APPROVED", "DEPLOYED"}


class GuardError(RuntimeError):
    pass


def load_env_file(path: Path) -> None:
    if not path.is_file():
        raise GuardError(f"环境文件不存在: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, separator, value = line.partition("=")
        if separator and key.strip():
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def read_skill_name(skill_dir: Path) -> str:
    skill_md = skill_dir / "SKILL.md"
    try:
        lines = skill_md.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise GuardError(f"无法读取 {skill_dir.name}/SKILL.md: {exc}") from exc
    if not lines or lines[0].strip() != "---":
        raise GuardError(f"{skill_dir.name} 目录解析失败，SKILL.md 缺少 name 字段")
    for line in lines[1:]:
        text = line.strip()
        if text == "---":
            break
        if text.startswith("name:"):
            name = text.split(":", 1)[1].strip().strip("\"'")
            if name:
                return name
    raise GuardError(f"{skill_dir.name} 目录解析失败，SKILL.md 缺少 name 字段")


def _normalize_path_part(value: str) -> str:
    try:
        return value.encode("cp437").decode("utf-8")
    except UnicodeError:
        return value


def compute_signature(skill_dir: Path) -> str:
    parts: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(skill_dir)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        rel = "/".join(_normalize_path_part(part) for part in relative.parts)
        parts.append(f"{rel}:{digest.hexdigest()}\n")
    content = "".join(parts).encode()
    return hashlib.sha256(content).hexdigest()


def skill_roots(cwd: Path) -> list[Path]:
    configured = os.environ.get("AGENT_MANAGER_CODEX_SKILLS_DIRS", "").strip()
    configured_roots: list[Path] = []
    if configured:
        configured_roots = [
            Path(item).expanduser().resolve()
            for item in configured.split(os.pathsep)
            if item.strip()
        ]
        missing = [str(path) for path in configured_roots if not path.is_dir()]
        if missing:
            raise GuardError(f"受治理的 Skill 目录不存在: {', '.join(missing)}")

    roots = list(configured_roots)
    current = cwd.resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".agents" / "skills"
        if candidate.is_dir():
            roots.append(candidate)
        if (directory / ".git").exists():
            break
    for candidate in (
        Path.home() / ".agents" / "skills",
        Path.home() / ".codex" / "skills",
        Path("/etc/codex/skills"),
    ):
        if candidate.is_dir():
            roots.append(candidate)
    return list(dict.fromkeys(path.resolve() for path in roots))


def discover_skills(cwd: Path) -> list[Path]:
    skills: list[Path] = []
    for root in skill_roots(cwd):
        if (root / "SKILL.md").is_file():
            skills.append(root.resolve())
        else:
            skills.extend(path.parent.resolve() for path in sorted(root.glob("*/SKILL.md")))
    return list(dict.fromkeys(skills))


def _api_error_detail(exc: urllib.error.HTTPError) -> str:
    raw = exc.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw or str(exc)
    return str(payload.get("detail") or payload.get("reason") or raw) if isinstance(payload, dict) else raw


def verify_skill(skill_dir: Path, turn_id: str) -> None:
    server = (
        os.environ.get("AGENT_MANAGER_VERIFIER_BASE_URL")
        or os.environ.get("AGENT_MANAGER_BASE_URL")
        or ""
    ).rstrip("/")
    token = (
        os.environ.get("AGENT_MANAGER_VERIFIER_TOKEN")
        or os.environ.get("AGENT_MANAGER_API_TOKEN")
        or ""
    ).strip()
    agent_id = (os.environ.get("AGENT_ID") or "").strip()
    if not server:
        raise GuardError("缺少 Agent Manager 地址，请设置 AGENT_MANAGER_VERIFIER_BASE_URL")
    if not token:
        raise GuardError("缺少运行凭证，请设置 AGENT_MANAGER_VERIFIER_TOKEN")
    if not agent_id:
        raise GuardError("缺少 Agent 身份，请设置 AGENT_ID")

    name = read_skill_name(skill_dir)
    body = json.dumps({
        "skill_name": name,
        "local_signature": compute_signature(skill_dir),
        "agent_id": agent_id,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{server}/api/v1/access/runtime/verify-skill-signature",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Agent-ID": agent_id,
            "X-Codex-Turn-ID": turn_id,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GuardError(f"Skill {name!r} 验证失败: {_api_error_detail(exc)}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GuardError(f"无法连接 Agent Manager，已阻断 Skill {name!r}: {exc}") from exc
    except (json.JSONDecodeError, TypeError) as exc:
        raise GuardError(f"Agent Manager 返回异常，已阻断 Skill {name!r}") from exc

    if not isinstance(payload, dict):
        raise GuardError(f"Agent Manager 返回异常，已阻断 Skill {name!r}")
    status = str(payload.get("status") or "")
    if not payload.get("allowed") or status not in LOADABLE_STATUSES:
        reason = payload.get("reason") or f"状态 {status or 'UNKNOWN'} 不允许加载"
        raise GuardError(f"Skill {name!r} 验证失败: {reason}")


def evaluate(event: dict[str, Any]) -> str | None:
    if event.get("hook_event_name") != "PreToolUse":
        return None
    cwd = Path(str(event.get("cwd") or "."))
    skills = discover_skills(cwd)
    for skill_dir in skills:
        verify_skill(skill_dir, str(event.get("turn_id") or ""))
    return None


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Agent Manager 强制校验阻断: {reason}",
        }
    }, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    try:
        if args.env_file:
            load_env_file(args.env_file.expanduser())
        raw = sys.stdin.read()
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise GuardError("Codex Hook 输入格式错误")
        evaluate(event)
    except (GuardError, json.JSONDecodeError) as exc:
        deny(str(exc))
    except Exception as exc:
        deny(f"Hook 执行异常: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
