import json
import logging
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..config import settings
from ..client_signing import (
    build_manifest,
    canonical_manifest,
    compute_content_signature,
    public_key_base64,
    sign_manifest,
)
from ..sqlite_db import get_db
from .access_tokens import resolve_access_token
from agent_manager.api.router import get_manager
from agent_manager.core.manager import AgentManager
from agent_manager.core.llm import LLMConfig
from agent_manager.core.models import AuditEvent, SkillStatus
from agent_manager.core.sandbox import SandboxConfig
from agent_manager.core.skillspector import is_skillspector_available
from agent_manager.core.text_reader import read_text_fallback


router = APIRouter(prefix="/v1/clients", tags=["clients"])
logger = logging.getLogger(__name__)
_CLIENT_RELEASE_DIR = Path(__file__).resolve().parents[2] / "scanner" / "releases"
_CLIENT_ONLINE_WINDOW = timedelta(minutes=10)
_CLIENT_DOWNLOAD_COOKIE = "agent_manager_client_download"
_CLIENT_DOWNLOAD_PURPOSE = "client_installer_download"
_CLIENT_DOWNLOAD_TICKET_TTL = timedelta(minutes=5)
_CLIENT_INSTALLER_RE = re.compile(
    r"^agent-manager-client-(?P<version>\d{2}\.\d{2}\.\d{2}(?:\.[1-9]\d?)?)-"
    r"(?P<platform>darwin-aarch64|darwin-x86_64|windows-x86_64|linux-x86_64)"
    r"(?P<extension>\.dmg|\.exe|\.AppImage)$"
)
_CLIENT_PLATFORM_LABELS = {
    "darwin-aarch64": "macOS Apple 芯片",
    "darwin-x86_64": "macOS Intel",
    "windows-x86_64": "Windows 64 位",
    "linux-x86_64": "Linux 64 位",
}


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value: str | None, default):
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def _client_release_version_key(value: str) -> tuple[int, int, int, int]:
    parts = tuple(map(int, value.split(".")))
    if len(parts) == 3:
        return (*parts, 0)
    if len(parts) == 4:
        return parts
    raise ValueError(f"invalid client release version: {value}")


def _runtime_token(
    scope: str,
    authorization: str | None,
    request: Request,
    db: Session,
) -> models.AccessToken:
    token = resolve_access_token(db, authorization, required_scope=scope, request=request)
    if token.token_type != "client":
        raise HTTPException(status_code=403, detail="当前凭证不是客户端接入凭证")
    return token


def _client_installer_path(platform: str) -> tuple[str, Path]:
    if "/" in platform or "\\" in platform or ".." in platform:
        raise HTTPException(status_code=400, detail="无效的客户端平台")
    filename = f"agent-manager-client-{platform}"
    if not _CLIENT_INSTALLER_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="无效的客户端安装包")
    path = _CLIENT_RELEASE_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"客户端文件不存在: {filename}")
    return filename, path


def _bind_client(token: models.AccessToken, client_id: str, db: Session) -> None:
    if token.bound_client_id and token.bound_client_id != client_id:
        raise HTTPException(status_code=403, detail="客户端凭证已绑定其他客户端")
    if not token.bound_client_id:
        token.bound_client_id = client_id
        db.commit()


def _client_or_404(db: Session, client_id: str) -> models.ManagedClient:
    row = db.query(models.ManagedClient).filter(models.ManagedClient.client_id == client_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户端不存在")
    return row


def _ensure_visible(row: models.ManagedClient, user: models.User) -> None:
    if user.role != "super_admin" and row.registered_by != user.username:
        raise HTTPException(status_code=404, detail="客户端不存在")


def _operation(db: Session, user: models.User, action: str, target: str, details: str) -> None:
    db.add(
        models.OperationLog(
            username=user.username,
            action=action,
            target=target,
            details=details,
        )
    )


def _token_can_use_agent(db: Session, token: models.AccessToken, agent: models.ManagedAgent) -> bool:
    if not agent.created_by or agent.created_by == token.created_by:
        return True
    owner = db.query(models.User).filter(models.User.username == token.created_by).first()
    return bool(owner and owner.role == "super_admin")


def _manager_trusted_skill(manager, skill_id: str):
    if hasattr(manager, "get_trusted_skill"):
        return manager.get_trusted_skill(skill_id)
    return manager.get_skill(skill_id)


def _manager_skill_versions(manager, skill_id: str):
    if hasattr(manager, "list_skill_versions"):
        return manager.list_skill_versions(skill_id)
    entry = manager.get_skill(skill_id)
    return [entry] if entry else []


def _manager_skills_by_names(manager, names: set[str]):
    if hasattr(manager, "list_skills_by_names"):
        return manager.list_skills_by_names(names)
    return [
        entry
        for entry in manager.list_skills()
        if entry.name in names
    ]


def _authorized_client_skill(
    db: Session,
    manager: AgentManager,
    client: models.ManagedClient,
    token: models.AccessToken,
    skill_id: str,
    version_id: str | None,
    agent_type: str | None,
    managed_agent_id: str | None,
):
    entry = manager.registry.get_by_id(version_id) if version_id and hasattr(manager, "registry") else _manager_trusted_skill(manager, skill_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    entry_family_id = getattr(entry, "family_id", None)
    if version_id and entry_family_id and entry_family_id != skill_id and entry.skill_id != skill_id:
        raise HTTPException(status_code=404, detail="Skill 版本不存在")
    agent = None
    if managed_agent_id:
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == managed_agent_id).first()
    bindings = (
        db.query(models.ClientAgent)
        .filter(
            models.ClientAgent.client_id == client.client_id,
            models.ClientAgent.skill_management_supported.is_(True),
        )
        .all()
    )
    if agent_type:
        bindings = [binding for binding in bindings if binding.agent_type == agent_type]
    elif agent:
        bindings = [binding for binding in bindings if _agent_kind(binding.agent_type) == _agent_kind(agent.channel)]
    binding = bindings[0] if len(bindings) == 1 else None
    if not binding:
        raise HTTPException(status_code=403, detail="客户端未发现支持 Skill 管理的目标 Agent")
    if client.governance_mode == "strict":
        if not agent or binding.managed_agent_id != managed_agent_id or not _token_can_use_agent(db, token, agent):
            raise HTTPException(status_code=403, detail="客户端未绑定该智能体")
        allowed_refs = {str(item) for item in _load(agent.skill_names_json, [])}
        if entry.name not in allowed_refs and entry.skill_id not in allowed_refs and (entry_family_id or "") not in allowed_refs:
            raise HTTPException(status_code=403, detail="智能体未授权使用该 Skill")
    if entry.status not in (SkillStatus.APPROVED, SkillStatus.DEPLOYED) or not entry.skill_path:
        raise HTTPException(status_code=403, detail="Skill 尚未批准或文件不可用")
    return entry


def _skill_display_metadata(name: str, description: str = "", root: Path | None = None) -> tuple[str, str]:
    generated_name = len(name) == 32 and all(character in "0123456789abcdef" for character in name.lower())
    if not generated_name or not root:
        return name, description
    meta_path = root / "_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        display_name = str(meta.get("slug") or "").strip()
    except (OSError, json.JSONDecodeError, AttributeError):
        display_name = ""
    try:
        content, _encoding = read_text_fallback(root / "SKILL.md")
    except OSError:
        content = ""
    lines = content.splitlines()
    if not display_name:
        display_name = next((line.lstrip("#").strip() for line in lines if line.startswith("# ")), "")
    if not description:
        heading_seen = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# "):
                heading_seen = True
            elif heading_seen and stripped and not stripped.startswith("#"):
                description = stripped
                break
    return display_name or name, description


def _update_platform_key(target: str, arch: str) -> str:
    normalized_target = {
        "macos": "darwin",
        "macosx": "darwin",
    }.get(target.lower(), target.lower())
    normalized_arch = {
        "arm64": "aarch64",
        "amd64": "x86_64",
        "x64": "x86_64",
    }.get(arch.lower(), arch.lower())
    return f"{normalized_target}-{normalized_arch}"


def _client_update_manifest(channel: str = "stable") -> dict | None:
    if channel not in {"stable", "preview"}:
        raise HTTPException(status_code=400, detail="无效的客户端更新通道")
    path = _CLIENT_RELEASE_DIR / ("preview.json" if channel == "preview" else "latest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if channel == "preview":
            return None
        raise HTTPException(status_code=404, detail="当前没有可用的客户端更新") from exc
    if not isinstance(value, dict) or not isinstance(value.get("platforms"), dict):
        raise HTTPException(status_code=500, detail="客户端更新清单格式错误")
    return value


def _matching_skill_entry(
    manager: AgentManager,
    local_skill: schemas.ClientSkillCompareItem,
    allowed_refs: set[str] | None = None,
    signature_cache: dict[str, str | None] | None = None,
    registry_entries: list | None = None,
):
    candidates = [
        entry
        for entry in (registry_entries if registry_entries is not None else manager.list_skills())
        if entry.name == local_skill.name
        and (allowed_refs is None or entry.skill_id in allowed_refs or entry.name in allowed_refs)
    ]
    fallback = candidates[0] if candidates else manager.get_skill(local_skill.name)
    for candidate in candidates:
        if not candidate.skill_path or not local_skill.signature:
            continue
        if _cached_skill_signature(candidate.skill_path, signature_cache) == local_skill.signature:
            return candidate
    return fallback


def _cached_skill_signature(skill_path: str, cache: dict[str, str | None] | None = None) -> str | None:
    if cache is not None and skill_path in cache:
        return cache[skill_path]
    try:
        signature = compute_content_signature(Path(skill_path))
    except (OSError, ValueError):
        signature = None
    if cache is not None:
        cache[skill_path] = signature
    return signature


def _replace_inventory(db: Session, client_id: str, agents: list[schemas.ClientAgentInventory]) -> None:
    existing_bindings = {
        row.agent_type: row.managed_agent_id
        for row in db.query(models.ClientAgent).filter(models.ClientAgent.client_id == client_id).all()
    }
    db.query(models.ClientSkillInstall).filter(models.ClientSkillInstall.client_id == client_id).delete()
    db.query(models.ClientAgent).filter(models.ClientAgent.client_id == client_id).delete()
    now = datetime.utcnow()
    for agent in agents:
        db.add(
            models.ClientAgent(
                client_id=client_id,
                agent_type=agent.agent_type,
                managed_agent_id=agent.managed_agent_id or existing_bindings.get(agent.agent_type),
                agent_version=agent.version,
                install_path=agent.install_path,
                skills_path=agent.skills_path,
                skill_management_supported=agent.skill_management_supported,
                capabilities_json=_dump(agent.capabilities),
                last_scanned_at=now,
            )
        )
        for skill in agent.skills:
            db.add(
                models.ClientSkillInstall(
                    client_id=client_id,
                    agent_type=agent.agent_type,
                    skill_id=skill.skill_id,
                    version_id=skill.version_id,
                    version_no=skill.version_no,
                    source_version=skill.source_version,
                    skill_name=skill.name,
                    skill_path=skill.path,
                    signature=skill.signature,
                    install_mode=skill.install_mode,
                    status=skill.status,
                    verified_at=now,
                )
            )
    db.flush()


def _agent_kind(value: str | None) -> str:
    normalized = "".join(character for character in (value or "").lower() if character.isalnum())
    return {
        "claude": "claudecode",
        "claudecode": "claudecode",
        "claudesktop": "claudedesktop",
        "geminicli": "gemini",
    }.get(normalized, normalized)


def _auto_match_agents(db: Session, client_id: str, owner: str | None) -> None:
    candidates = db.query(models.ManagedAgent).filter(models.ManagedAgent.status == "active")
    if owner:
        candidates = candidates.filter(models.ManagedAgent.created_by == owner)
    by_kind: dict[str, list[models.ManagedAgent]] = {}
    for candidate in candidates.all():
        by_kind.setdefault(_agent_kind(candidate.channel), []).append(candidate)
    for local in db.query(models.ClientAgent).filter(models.ClientAgent.client_id == client_id).all():
        matches = by_kind.get(_agent_kind(local.agent_type), [])
        if not local.managed_agent_id and len(matches) == 1:
            local.managed_agent_id = matches[0].agent_id


def _client_response(db: Session, row: models.ManagedClient) -> dict:
    agents = db.query(models.ClientAgent).filter(models.ClientAgent.client_id == row.client_id).all()
    skills = db.query(models.ClientSkillInstall).filter(models.ClientSkillInstall.client_id == row.client_id).all()
    latest_event_ids = (
        db.query(func.max(models.ClientEvent.id).label("event_id"))
        .filter(models.ClientEvent.client_id == row.client_id, models.ClientEvent.skill_name.is_not(None))
        .group_by(models.ClientEvent.agent_type, models.ClientEvent.skill_name)
        .subquery()
    )
    issue_count = (
        db.query(models.ClientEvent)
        .join(latest_event_ids, models.ClientEvent.id == latest_event_ids.c.event_id)
        .filter(models.ClientEvent.event_type.in_(("unmanaged_skill_found", "skill_modified", "skill_blocked", "skill_quarantined")))
        .count()
    )
    online = bool(row.last_seen_at and datetime.utcnow() - row.last_seen_at <= _CLIENT_ONLINE_WINDOW)
    return {
        "client_id": row.client_id,
        "name": row.name,
        "hostname": row.hostname,
        "os": row.os,
        "arch": row.arch,
        "client_version": row.client_version,
        "governance_mode": row.governance_mode,
        "policy_mode": row.policy_mode,
        "status": "online" if online else "offline",
        "last_seen_at": row.last_seen_at,
        "registered_by": row.registered_by,
        "created_at": row.created_at,
        "issue_count": issue_count,
        "agents": [
            {
                "agent_type": agent.agent_type,
                "managed_agent_id": agent.managed_agent_id,
                "version": agent.agent_version,
                "install_path": agent.install_path,
                "skills_path": agent.skills_path,
                "skill_management_supported": agent.skill_management_supported,
                "capabilities": _load(agent.capabilities_json, {}),
                "takeover_status": agent.takeover_status,
                "skills": [
                    {
                        "skill_id": skill.skill_id,
                        "version_id": skill.version_id,
                        "version_no": skill.version_no,
                        "source_version": skill.source_version,
                        "name": skill.skill_name,
                        "path": skill.skill_path,
                        "signature": skill.signature,
                        "install_mode": skill.install_mode,
                        "status": skill.status,
                    }
                    for skill in skills
                    if skill.agent_type == agent.agent_type
                ],
            }
            for agent in agents
        ],
    }


def _client_policy_response(db: Session, row: models.ManagedClient) -> dict:
    bindings = db.query(models.ClientAgent).filter(models.ClientAgent.client_id == row.client_id).all()
    return {
        "mode": row.policy_mode,
        "governance_mode": row.governance_mode,
        "light_scan_seconds": 300,
        "full_scan_seconds": 1800,
        "release_public_key": public_key_base64(),
        "agent_bindings": {
            binding.agent_type: binding.managed_agent_id
            for binding in bindings
            if binding.managed_agent_id
        },
    }


def _task_history(db: Session, client_id: str, limit: int = 100) -> list[dict]:
    return [
        {
            "id": task.id,
            "task_type": task.task_type,
            "payload": _load(task.payload_json, {}),
            "status": task.status,
            "error": task.error,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }
        for task in (
            db.query(models.ClientTask)
            .filter(models.ClientTask.client_id == client_id)
            .order_by(models.ClientTask.id.desc())
            .limit(limit)
            .all()
        )
    ]


def _event_history(db: Session, client_id: str, limit: int = 100) -> list[dict]:
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "agent_type": event.agent_type,
            "skill_name": event.skill_name,
            "details": _load(event.details_json, {}),
            "created_at": event.created_at,
        }
        for event in (
            db.query(models.ClientEvent)
            .filter(models.ClientEvent.client_id == client_id)
            .filter(models.ClientEvent.event_type.notin_(("client_registered", "takeover_completed")))
            .order_by(models.ClientEvent.id.desc())
            .limit(limit)
            .all()
        )
    ]


@router.post("/register")
def register_client(
    body: schemas.ClientRegisterRequest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:register", authorization, request, db)
    _bind_client(token, body.client_id, db)
    row = db.query(models.ManagedClient).filter(models.ManagedClient.client_id == body.client_id).first()
    is_new = row is None
    if is_new:
        row = models.ManagedClient(client_id=body.client_id, registered_by=token.created_by)
        db.add(row)
    row.name = body.name.strip() or body.hostname
    row.hostname = body.hostname
    row.os = body.os
    row.arch = body.arch
    row.client_version = body.client_version
    row.status = "online"
    row.last_seen_at = datetime.utcnow()
    _replace_inventory(db, body.client_id, body.agents)
    _auto_match_agents(db, body.client_id, token.created_by)
    if is_new:
        db.add(models.ClientEvent(client_id=body.client_id, event_type="client_registered"))
    db.commit()
    return _client_response(db, row)


@router.post("/{client_id}/heartbeat")
def heartbeat(
    client_id: str,
    body: schemas.ClientHeartbeatRequest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:heartbeat", authorization, request, db)
    _bind_client(token, client_id, db)
    if body.client_id != client_id:
        raise HTTPException(status_code=400, detail="client_id 不一致")
    row = _client_or_404(db, client_id)
    row.last_seen_at = datetime.utcnow()
    row.status = "online"
    if body.client_version:
        row.client_version = body.client_version
    db.commit()
    return {"ok": True, "last_seen_at": row.last_seen_at, "policy": _client_policy_response(db, row)}


@router.get("/{client_id}/policy")
def get_client_policy(
    client_id: str,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:read-policy", authorization, request, db)
    _bind_client(token, client_id, db)
    row = _client_or_404(db, client_id)
    return _client_policy_response(db, row)


@router.get("/{client_id}/status")
def get_client_runtime_status(
    client_id: str,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:read-policy", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    client.last_seen_at = datetime.utcnow()
    client.status = "online"
    db.commit()
    result = _client_response(db, client)
    llm_config = LLMConfig.load()
    sandbox_config = SandboxConfig.load()
    result["detection_capabilities"] = {
        "rules": {"enabled": True, "label": "规则扫描"},
        "deep_scan": {"enabled": is_skillspector_available(), "label": "深度扫描"},
        "sandbox": {"enabled": sandbox_config.enabled, "label": "Sandbox"},
        "llm": {
            "enabled": llm_config.is_ready,
            "label": "LLM 分析",
            "detail": llm_config.model if llm_config.is_ready else None,
        },
    }
    agents = db.query(models.ManagedAgent).filter(models.ManagedAgent.status == "active")
    owner = db.query(models.User).filter(models.User.username == token.created_by).first()
    if not owner or owner.role != "super_admin":
        agents = agents.filter(models.ManagedAgent.created_by == token.created_by)
    result["available_managed_agents"] = [
        {"agent_id": agent.agent_id, "name": agent.name, "channel": agent.channel}
        for agent in agents.order_by(models.ManagedAgent.name.asc()).all()
    ]
    result["tasks"] = _task_history(db, client_id, 20)
    result["events"] = _event_history(db, client_id, 50)
    return result


@router.post("/{client_id}/inventory")
def report_inventory(
    client_id: str,
    body: schemas.ClientInventoryRequest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:report-inventory", authorization, request, db)
    _bind_client(token, client_id, db)
    row = _client_or_404(db, client_id)
    _replace_inventory(db, client_id, body.agents)
    _auto_match_agents(db, client_id, token.created_by)
    row.last_seen_at = datetime.utcnow()
    row.status = "online"
    db.commit()
    return _client_response(db, row)


@router.post("/{client_id}/events")
def report_event(
    client_id: str,
    body: schemas.ClientEventCreate,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_manager),
):
    token = _runtime_token("client:report-events", authorization, request, db)
    _bind_client(token, client_id, db)
    _client_or_404(db, client_id)
    row = models.ClientEvent(
        client_id=client_id,
        event_type=body.event_type,
        agent_type=body.agent_type,
        skill_name=body.skill_name,
        details_json=_dump(body.details),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    details = {
        **body.details,
        "client_id": client_id,
        "agent_id": body.agent_type,
        "client_ip": request.client.host if request.client else None,
        "token_name": token.name,
        "token_type": token.token_type,
        "source": "managed_client",
    }
    try:
        manager.registry.log_event(
            AuditEvent(
                event_id=f"client-event-{client_id}-{row.id}",
                event_type=body.event_type,
                skill_id=str(body.details.get("skill_id") or "unknown"),
                skill_name=body.skill_name or "-",
                actor=client_id,
                details=details,
            )
        )
    except sqlite3.OperationalError as exc:
        logger.warning("Could not project client event %s into audit: %s", row.id, exc)
    return {"ok": True, "event_id": row.id}


@router.post("/{client_id}/takeover-report")
def report_takeover(
    client_id: str,
    body: schemas.ClientTakeoverReport,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:report-events", authorization, request, db)
    _bind_client(token, client_id, db)
    _client_or_404(db, client_id)
    if body.managed_count == 0 and body.pending_count == 0:
        return {"ok": True, "recorded": False}
    db.add(
        models.ClientEvent(
            client_id=client_id,
            event_type="takeover_completed",
            details_json=_dump(body.model_dump()),
        )
    )
    db.commit()
    return {"ok": True, "recorded": True}


@router.get("/{client_id}/tasks")
def poll_tasks(
    client_id: str,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(token, client_id, db)
    _client_or_404(db, client_id)
    rows = (
        db.query(models.ClientTask)
        .filter(models.ClientTask.client_id == client_id, models.ClientTask.status == "pending")
        .order_by(models.ClientTask.id.asc())
        .all()
    )
    return [{"id": row.id, "task_type": row.task_type, "payload": _load(row.payload_json, {})} for row in rows]


@router.post("/{client_id}/tasks/{task_id}/result")
def report_task_result(
    client_id: str,
    task_id: int,
    body: schemas.ClientTaskResult,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(token, client_id, db)
    row = (
        db.query(models.ClientTask)
        .filter(models.ClientTask.id == task_id, models.ClientTask.client_id == client_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row.status == "cancelled":
        return {"ok": True, "ignored": True}
    row.status = body.status
    row.error = body.error
    if body.status == "running":
        row.started_at = datetime.utcnow()
    else:
        row.finished_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.get("")
def list_clients(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    query = db.query(models.ManagedClient)
    if current_user.role != "super_admin":
        query = query.filter(models.ManagedClient.registered_by == current_user.username)
    return [_client_response(db, row) for row in query.order_by(models.ManagedClient.id.desc()).all()]


@router.get("/downloads/available")
def list_client_downloads(
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    items = []
    for path in _CLIENT_RELEASE_DIR.glob("agent-manager-client-*"):
        match = _CLIENT_INSTALLER_RE.match(path.name)
        if path.is_file() and match:
            value = match.groupdict()
            items.append({
                "key": path.name.removeprefix("agent-manager-client-"),
                "filename": path.name,
                "size": path.stat().st_size,
                "version": value["version"],
                "platform": value["platform"],
                "platform_label": _CLIENT_PLATFORM_LABELS[value["platform"]],
            })
    if not items:
        return {"items": []}
    latest_version = max(_client_release_version_key(item["version"]) for item in items)
    latest_items = [
        item
        for item in items
        if _client_release_version_key(item["version"]) == latest_version
    ]
    latest_items.sort(key=lambda item: item["platform"])
    return {"items": latest_items}


@router.post("/downloads/ticket")
def create_client_download_ticket(
    response: Response,
    platform: str = Query(...),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    filename, _ = _client_installer_path(platform)
    ticket = auth.create_access_token(
        {
            "download_user": current_user.username,
            "purpose": _CLIENT_DOWNLOAD_PURPOSE,
            "platform": platform,
        },
        expires_delta=_CLIENT_DOWNLOAD_TICKET_TTL,
    )
    response.set_cookie(
        key=_CLIENT_DOWNLOAD_COOKIE,
        value=ticket,
        max_age=int(_CLIENT_DOWNLOAD_TICKET_TTL.total_seconds()),
        httponly=True,
        samesite="strict",
        path="/api/v1/clients/downloads/file",
    )
    return {
        "url": f"/api/v1/clients/downloads/file?platform={platform}",
        "filename": filename,
        "expires_in": int(_CLIENT_DOWNLOAD_TICKET_TTL.total_seconds()),
    }


@router.get("/downloads/file")
def download_client_binary(
    platform: str = Query(...),
    download_ticket: str | None = Cookie(None, alias=_CLIENT_DOWNLOAD_COOKIE),
):
    if not download_ticket:
        raise HTTPException(status_code=401, detail="下载票据缺失或已过期，请重新点击下载")
    try:
        payload = jwt.decode(download_ticket, settings.SECRET_KEY, algorithms=[auth.ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="下载票据无效或已过期，请重新点击下载") from exc
    if (
        payload.get("purpose") != _CLIENT_DOWNLOAD_PURPOSE
        or payload.get("platform") != platform
        or not payload.get("download_user")
    ):
        raise HTTPException(status_code=403, detail="下载票据与安装包不匹配，请重新点击下载")
    filename, path = _client_installer_path(platform)
    return FileResponse(
        path,
        filename=filename,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/updates/{target}/{arch}/{current_version}", name="check_client_update")
def check_client_update(
    target: str,
    arch: str,
    current_version: str,
    request: Request,
    authorization: str | None = Header(None),
    channel: str = Query("stable"),
    db: Session = Depends(get_db),
):
    _runtime_token("client:read-policy", authorization, request, db)
    manifest = _client_update_manifest(channel)
    if manifest is None:
        return Response(status_code=204)
    platform = manifest["platforms"].get(_update_platform_key(target, arch))
    if not isinstance(platform, dict):
        raise HTTPException(status_code=404, detail="当前平台没有可用的客户端更新")
    filename = str(platform.get("file") or "")
    signature = str(platform.get("signature") or "")
    if not filename or not signature or Path(filename).name != filename:
        raise HTTPException(status_code=500, detail="客户端更新清单内容无效")
    if not (_CLIENT_RELEASE_DIR / filename).is_file():
        raise HTTPException(status_code=404, detail="客户端更新包不存在")
    return {
        "version": str(manifest.get("version") or current_version),
        "notes": str(manifest.get("notes") or ""),
        "pub_date": manifest.get("pub_date"),
        "url": str(request.url_for("download_client_update", filename=filename)),
        "signature": signature,
    }


@router.get("/updates/files/{filename}", name="download_client_update")
def download_client_update(
    filename: str,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    _runtime_token("client:read-policy", authorization, request, db)
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="无效的客户端更新文件")
    path = _CLIENT_RELEASE_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="客户端更新包不存在")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


@router.get("/{client_id}")
def get_client(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _client_or_404(db, client_id)
    _ensure_visible(row, current_user)
    result = _client_response(db, row)
    result["tasks"] = _task_history(db, client_id)
    result["events"] = _event_history(db, client_id)
    return result


@router.get("/{client_id}/inventory")
def get_client_inventory(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _client_or_404(db, client_id)
    _ensure_visible(row, current_user)
    return {"client_id": client_id, "agents": _client_response(db, row)["agents"]}


@router.put("/{client_id}/policy")
def update_client_policy(
    client_id: str,
    body: schemas.ClientPolicyUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _client_or_404(db, client_id)
    _ensure_visible(row, current_user)
    if body.mode is None and body.governance_mode is None:
        raise HTTPException(status_code=400, detail="至少提供一项客户端策略")
    if body.mode is not None:
        row.policy_mode = body.mode
    if body.governance_mode is not None:
        row.governance_mode = body.governance_mode
    _operation(
        db,
        current_user,
        "更新客户端策略",
        client_id,
        f"mode={row.policy_mode}, governance_mode={row.governance_mode}",
    )
    payload = {
        "reason": "policy_changed",
        "mode": row.policy_mode,
        "governance_mode": row.governance_mode,
    }
    sync_task = next(
        (
            task
            for task in (
                db.query(models.ClientTask)
                .filter(
                    models.ClientTask.client_id == client_id,
                    models.ClientTask.task_type == "rescan",
                    models.ClientTask.status == "pending",
                )
                .all()
            )
            if _load(task.payload_json, {}).get("reason") == "policy_changed"
        ),
        None,
    )
    if sync_task:
        sync_task.payload_json = _dump(payload)
    else:
        sync_task = models.ClientTask(client_id=client_id, task_type="rescan", payload_json=_dump(payload))
        db.add(sync_task)
    db.commit()
    return {
        "client_id": client_id,
        "mode": row.policy_mode,
        "governance_mode": row.governance_mode,
        "sync_task_id": sync_task.id,
    }


@router.put("/{client_id}/agents/{agent_type}")
def bind_client_agent(
    client_id: str,
    agent_type: str,
    body: schemas.ClientAgentBindingUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    client = _client_or_404(db, client_id)
    _ensure_visible(client, current_user)
    row = (
        db.query(models.ClientAgent)
        .filter(models.ClientAgent.client_id == client_id, models.ClientAgent.agent_type == agent_type)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="本地 Agent 不存在")
    if body.managed_agent_id:
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == body.managed_agent_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail="平台智能体不存在")
        if current_user.role != "super_admin" and agent.created_by != current_user.username:
            raise HTTPException(status_code=404, detail="平台智能体不存在")
        if _agent_kind(agent.channel) != _agent_kind(agent_type):
            raise HTTPException(status_code=400, detail="平台智能体类型与本地 Agent 不一致")
    row.managed_agent_id = body.managed_agent_id
    _operation(
        db,
        current_user,
        "更新本地 Agent 映射",
        client_id,
        f"agent_type={agent_type}, managed_agent_id={body.managed_agent_id or '-'}",
    )
    db.commit()
    return {"client_id": client_id, "agent_type": agent_type, "managed_agent_id": row.managed_agent_id}


@router.post("/{client_id}/tasks")
def create_task(
    client_id: str,
    body: schemas.ClientTaskCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
    manager: AgentManager = Depends(get_manager),
):
    client = _client_or_404(db, client_id)
    _ensure_visible(client, current_user)
    payload = dict(body.payload)
    if body.task_type in {"install_skill", "repair_skill"}:
        skill_id = str(payload.get("skill_id") or "")
        managed_agent_id = str(payload.get("managed_agent_id") or "")
        agent_type = str(payload.get("agent_type") or "")
        version_id = str(payload.get("version_id") or "")
        entry = manager.registry.get_by_id(version_id) if version_id and hasattr(manager, "registry") else _manager_trusted_skill(manager, skill_id)
        client_agent = (
            db.query(models.ClientAgent)
            .filter(
                models.ClientAgent.client_id == client_id,
                models.ClientAgent.agent_type == agent_type,
                models.ClientAgent.skill_management_supported.is_(True),
            )
            .first()
        )
        entry_family_id = getattr(entry, "family_id", None) if entry else None
        if version_id and entry and entry.skill_id != skill_id and entry_family_id != skill_id:
            raise HTTPException(status_code=400, detail="指定版本不属于该 Skill")
        if not entry or entry.status not in (SkillStatus.APPROVED, SkillStatus.DEPLOYED):
            raise HTTPException(status_code=400, detail="只能安装已批准的 Skill")
        payload["skill_id"] = entry_family_id or entry.skill_id
        payload["version_id"] = entry.skill_id
        payload["skill_name"] = _skill_display_metadata(
            entry.name,
            getattr(entry, "description", ""),
            Path(entry.skill_path) if getattr(entry, "skill_path", None) else None,
        )[0]
        if not client_agent:
            raise HTTPException(status_code=400, detail="客户端未发现支持 Skill 管理的目标 Agent")
        if client.governance_mode == "strict":
            agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == managed_agent_id).first()
            if not agent:
                raise HTTPException(status_code=404, detail="智能体不存在")
            if client_agent.managed_agent_id != managed_agent_id:
                raise HTTPException(status_code=400, detail="本地 Agent 尚未绑定该平台智能体")
            allowed_refs = {str(item) for item in _load(agent.skill_names_json, [])}
            if entry.name not in allowed_refs and entry.skill_id not in allowed_refs and (getattr(entry, "family_id", None) or "") not in allowed_refs:
                raise HTTPException(status_code=403, detail="智能体未授权使用该 Skill")
        else:
            payload.pop("managed_agent_id", None)
    elif body.task_type == "remove_skill":
        agent_type = str(payload.get("agent_type") or "")
        skill_id = str(payload.get("skill_id") or "")
        install = (
            db.query(models.ClientSkillInstall)
            .join(
                models.ClientAgent,
                (models.ClientAgent.client_id == models.ClientSkillInstall.client_id)
                & (models.ClientAgent.agent_type == models.ClientSkillInstall.agent_type),
            )
            .filter(
                models.ClientSkillInstall.client_id == client_id,
                models.ClientSkillInstall.agent_type == agent_type,
                models.ClientSkillInstall.skill_id == skill_id,
                models.ClientAgent.skill_management_supported.is_(True),
            )
            .first()
        )
        if not install:
            raise HTTPException(status_code=400, detail="客户端中不存在可移除的受管 Skill")
        payload["skill_name"] = install.skill_name
    for pending in (
        db.query(models.ClientTask)
        .filter(
            models.ClientTask.client_id == client_id,
            models.ClientTask.task_type == body.task_type,
            models.ClientTask.status.in_(("pending", "running")),
        )
        .all()
    ):
        if _load(pending.payload_json, {}) == payload:
            return {"id": pending.id, "status": pending.status}
    row = models.ClientTask(client_id=client_id, task_type=body.task_type, payload_json=_dump(payload))
    db.add(row)
    _operation(db, current_user, "创建客户端任务", client_id, f"task_type={body.task_type}")
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/{client_id}/tasks/{task_id}/cancel")
def cancel_task(
    client_id: str,
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    client = _client_or_404(db, client_id)
    _ensure_visible(client, current_user)
    row = db.query(models.ClientTask).filter(models.ClientTask.id == task_id, models.ClientTask.client_id == client_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row.status not in {"pending", "running"}:
        raise HTTPException(status_code=400, detail="只有待执行或执行中的任务可以取消")
    row.status = "cancelled"
    row.finished_at = datetime.utcnow()
    _operation(db, current_user, "取消客户端任务", client_id, f"task_id={task_id}")
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/{client_id}/tasks/{task_id}/retry")
def retry_task(
    client_id: str,
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    client = _client_or_404(db, client_id)
    _ensure_visible(client, current_user)
    row = db.query(models.ClientTask).filter(models.ClientTask.id == task_id, models.ClientTask.client_id == client_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="只有失败或已取消的任务可以重试")
    row.status = "pending"
    row.error = None
    row.started_at = None
    row.finished_at = None
    _operation(db, current_user, "重试客户端任务", client_id, f"task_id={task_id}")
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/{client_id}/compare")
def compare_inventory(
    client_id: str,
    body: schemas.ClientCompareRequest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_manager),
):
    token = _runtime_token("client:report-inventory", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    result = []
    bindings_changed = False
    signature_cache: dict[str, str | None] = {}
    skill_names = {
        skill.name
        for agent_item in body.agents
        for skill in agent_item.skills
        if skill.name
    }
    registry_entries = _manager_skills_by_names(manager, skill_names)
    for agent_item in body.agents:
        local_agent = (
            db.query(models.ClientAgent)
            .filter(
                models.ClientAgent.client_id == client_id,
                models.ClientAgent.agent_type == agent_item.agent_type,
                models.ClientAgent.skill_management_supported.is_(True),
            )
            .first()
        )
        managed_agent = None
        if agent_item.managed_agent_id:
            managed_agent = (
                db.query(models.ManagedAgent)
                .filter(models.ManagedAgent.agent_id == agent_item.managed_agent_id)
                .first()
            )
        if managed_agent and not _token_can_use_agent(db, token, managed_agent):
            managed_agent = None
        if managed_agent and _agent_kind(managed_agent.channel) != _agent_kind(agent_item.agent_type):
            managed_agent = None
        if local_agent and managed_agent:
            if local_agent.managed_agent_id and local_agent.managed_agent_id != managed_agent.agent_id:
                managed_agent = None
            elif not local_agent.managed_agent_id:
                local_agent.managed_agent_id = managed_agent.agent_id
                bindings_changed = True
        allowed_refs: set[str] | None = None
        if local_agent and managed_agent and managed_agent.status == "active":
            allowed_refs = {str(item) for item in _load(managed_agent.skill_names_json, [])}
        for local_skill in agent_item.skills:
            strict = client.governance_mode == "strict"
            entry = _matching_skill_entry(
                manager,
                local_skill,
                allowed_refs if strict else None,
                signature_cache,
                registry_entries,
            )
            expected_signature = _cached_skill_signature(entry.skill_path, signature_cache) if entry and entry.skill_path else None
            authorized = bool(
                not strict
                or (
                    managed_agent
                    and allowed_refs is not None
                    and (entry and (entry.name in allowed_refs or entry.skill_id in allowed_refs))
                )
            )
            allowed = bool(local_agent and entry and authorized and entry.status == SkillStatus.APPROVED and expected_signature and local_skill.signature == expected_signature)
            if not local_agent:
                reason = "local_agent_not_found"
            elif strict and not managed_agent:
                reason = "managed_agent_not_found"
            elif not entry:
                reason = "skill_not_found"
            elif strict and allowed_refs is not None and entry.name not in allowed_refs and entry.skill_id not in allowed_refs:
                reason = "agent_not_authorized"
            elif entry.status != SkillStatus.APPROVED:
                reason = "skill_not_approved"
            elif not expected_signature or local_skill.signature != expected_signature:
                reason = "signature_mismatch"
            else:
                reason = "allowed"
            result.append(
                {
                    "agent_type": agent_item.agent_type,
                    "managed_agent_id": agent_item.managed_agent_id,
                    "name": local_skill.name,
                    "local_path": local_skill.path,
                    "local_signature": local_skill.signature,
                    "skill_id": entry.skill_id if entry else None,
                    "status": entry.status.value if entry else None,
                    "expected_signature": expected_signature,
                    "allowed": allowed,
                    "reason": reason,
                }
            )
    if bindings_changed:
        db.commit()
    return {"items": result}


@router.get("/{client_id}/skills/available")
def list_available_client_skills(
    client_id: str,
    request: Request,
    agent_type: str = Query(...),
    managed_agent_id: str | None = Query(None),
    q: str | None = Query(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_manager),
):
    token = _runtime_token("client:download-approved-skill", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    binding = (
        db.query(models.ClientAgent)
        .filter(
            models.ClientAgent.client_id == client_id,
            models.ClientAgent.agent_type == agent_type,
            models.ClientAgent.skill_management_supported.is_(True),
        )
        .first()
    )
    if not binding:
        raise HTTPException(status_code=403, detail="客户端未发现支持 Skill 管理的目标 Agent")

    if client.governance_mode == "strict":
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == managed_agent_id).first()
        if not agent or binding.managed_agent_id != managed_agent_id or not _token_can_use_agent(db, token, agent):
            raise HTTPException(status_code=403, detail="客户端未绑定该智能体")
        entries = []
        seen = set()
        for ref in _load(agent.skill_names_json, []):
            entry = _manager_trusted_skill(manager, str(ref))
            if entry and entry.skill_id not in seen and entry.status == SkillStatus.APPROVED and entry.skill_path:
                display_name, _description = _skill_display_metadata(entry.name, entry.description, Path(entry.skill_path))
                item = {
                    "skill_id": getattr(entry, "family_id", None) or entry.skill_id,
                    "version_id": entry.skill_id,
                    "version_no": getattr(entry, "version_no", 1),
                    "source_version": getattr(entry, "source_version", None),
                    "name": display_name,
                    "status": entry.status.value,
                    "submitted_by": getattr(getattr(entry, "source", None), "author", None),
                }
                if getattr(entry, "submitted_at", None):
                    item["submitted_at"] = entry.submitted_at
                entries.append(item)
                seen.add(entry.skill_id)
    else:
        entries = manager.list_skill_summaries(
            page=1,
            page_size=100,
            statuses=[SkillStatus.APPROVED],
            trusted_only=True,
            q=q,
            sort_by="submitted_at",
            sort_order="desc",
        )["items"]
        for item in entries:
            entry = _manager_trusted_skill(manager, item["version_id"])
            if entry and entry.skill_path:
                item["name"], _description = _skill_display_metadata(
                    entry.name,
                    getattr(entry, "description", "") or "",
                    Path(entry.skill_path),
                )
    if q and client.governance_mode == "strict":
        needle = q.lower()
        entries = [item for item in entries if needle in item["name"].lower() or needle in item["skill_id"].lower()]
    if client.governance_mode == "strict":
        entries.sort(key=lambda item: str(item.get("submitted_at") or ""), reverse=True)
    return {"items": entries}


@router.get("/{client_id}/skills/{skill_id}/versions")
def list_available_client_skill_versions(
    client_id: str,
    skill_id: str,
    request: Request,
    agent_type: str | None = Query(None),
    managed_agent_id: str | None = Query(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_manager),
):
    token = _runtime_token("client:download-approved-skill", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    selected = _authorized_client_skill(
        db,
        manager,
        client,
        token,
        skill_id,
        None,
        agent_type,
        managed_agent_id,
    )
    versions = [
        entry
        for entry in _manager_skill_versions(manager, getattr(selected, "family_id", None) or selected.skill_id)
        if entry.status in (SkillStatus.APPROVED, SkillStatus.DEPLOYED) and entry.skill_path
    ]
    return {
        "skill_id": getattr(selected, "family_id", None) or selected.skill_id,
        "default_version_id": selected.skill_id,
        "items": [
            {
                "version_id": entry.skill_id,
                "version_no": getattr(entry, "version_no", 1),
                "source_version": getattr(entry, "source_version", None),
                "status": entry.status.value,
                "risk_level": entry.risk_level.value if entry.risk_level else None,
                "latest_trusted": entry.skill_id == selected.skill_id,
                "approved_at": entry.approved_at,
                "approved_by": entry.approved_by,
                "submitted_at": entry.submitted_at,
                "submitted_by": getattr(getattr(entry, "source", None), "author", None),
            }
            for entry in versions
        ],
    }


@router.get("/{client_id}/skills/{skill_id}/preview")
def preview_client_skill(
    client_id: str,
    skill_id: str,
    request: Request,
    agent_type: str | None = Query(None),
    managed_agent_id: str | None = Query(None),
    version_id: str | None = Query(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_manager),
):
    token = _runtime_token("client:download-approved-skill", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    entry = _authorized_client_skill(db, manager, client, token, skill_id, version_id, agent_type, managed_agent_id)
    risk_level = getattr(entry, "risk_level", None)
    display_name, description = _skill_display_metadata(
        entry.name,
        getattr(entry, "description", "") or "",
        Path(entry.skill_path),
    )
    return {
        "skill_id": getattr(entry, "family_id", None) or entry.skill_id,
        "version_id": entry.skill_id,
        "version_no": getattr(entry, "version_no", 1),
        "source_version": getattr(entry, "source_version", None),
        "name": display_name,
        "description": description,
        "status": entry.status.value,
        "risk_level": getattr(risk_level, "value", risk_level),
        "submitted_at": getattr(entry, "submitted_at", None),
        "submitted_by": getattr(getattr(entry, "source", None), "author", None),
    }


@router.get("/{client_id}/skills/{skill_id}/package")
def download_client_skill_package(
    client_id: str,
    skill_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    agent_type: str | None = Query(None),
    managed_agent_id: str | None = Query(None),
    version_id: str | None = Query(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_manager),
):
    token = _runtime_token("client:download-approved-skill", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    entry = _authorized_client_skill(db, manager, client, token, skill_id, version_id, agent_type, managed_agent_id)
    root = Path(entry.skill_path).resolve()
    display_name, _description = _skill_display_metadata(entry.name, getattr(entry, "description", "") or "", root)
    manifest = build_manifest(
        getattr(entry, "family_id", None) or entry.skill_id,
        display_name,
        root,
        compute_content_signature(root),
        version_id=entry.skill_id,
        version_no=getattr(entry, "version_no", 1),
        source_version=getattr(entry, "source_version", None),
        content_fingerprint=getattr(entry, "content_fingerprint", None),
    )
    signature = sign_manifest(manifest)
    tmp = tempfile.NamedTemporaryFile(prefix="agent-manager-client-skill-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", canonical_manifest(manifest))
        archive.writestr("manifest.sig", signature)
        for item in manifest["files"]:
            archive.write(root / item["path"], f"skill/{item['path']}")
    background_tasks.add_task(tmp_path.unlink, missing_ok=True)
    return FileResponse(tmp_path, filename=f"{display_name}.zip", media_type="application/zip")
