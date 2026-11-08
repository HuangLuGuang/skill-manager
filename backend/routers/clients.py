import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_manager.core.licensing import LicenseError, require_license, scan_allowed

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Query, Request, Response
from backend.client_event_delivery import save_delivery
from backend import client_discovery, client_governance, client_skill_actions, runtime_governance, client_event_records
from backend.agent_workspace import installation_owns_path
from backend.client_assets import asset_inventory, inventory_capabilities
from backend.model_switch import AGENTS as MODEL_ADAPTERS, validate_options as validate_model_options, validate_parameter_version, contract_for_version, validate_effective_parameters, reported_model_parameters
from backend.client_task_notifications import task_hub
from backend.external_ai_gateway import binding_models, ensure_binding
from backend.security_scan_controls import unprotect_secret
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.encoders import jsonable_encoder
from jose import JWTError, jwt
from pydantic import ValidationError
from sqlalchemy import and_, case, func, or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..api_errors import ApiError
from ..config import settings
from ..client_signing import (
    build_manifest,
    canonical_manifest,
    compute_content_signature,
    public_key_base64,
    sign_manifest,
)
from ..sqlite_db import get_db
from .access_tokens import _hash_token, _new_token, resolve_access_token
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
_MODEL_CONFIG_TASK_STALE_AFTER = timedelta(minutes=10)
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
_MODEL_CONFIG_AGENT_TYPES = set(MODEL_ADAPTERS)
_MODEL_CONFIG_AGENT_LABELS = {key: spec["label"] for key, spec in MODEL_ADAPTERS.items()}
_AUTO_AGENT_CREDENTIAL_SCOPES = [
    "runtime:verify-signature",
    "runtime:can-load",
    "runtime:check-tool",
    "model:chat",
]


def require_client_task(task_type):
    if task_type == "rescan":
        require_license("security_scanning")
    elif task_type in {"install_skill", "repair_skill"}:
        require_license("skill_governance")
    elif task_type == "apply_model_config":
        require_license("model_gateway")
    elif task_type in {"verify_model_config", "restore_model_config"}:
        require_license("model_gateway", runtime=True)
    elif task_type in {"aidr_plugin_action", "aidr_skill_observe"}:
        require_license("aidr", runtime=True)


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value: str | None, default):
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def _local_agent_id(value: str | None, agent_type: str) -> str:
    return (value or agent_type).strip() or agent_type


def _active_runtime_token(
    db: Session,
    agent_id: str,
    required_scope: str | None = None,
) -> models.AccessToken | None:
    rows = (
        db.query(models.AccessToken)
        .filter(
            models.AccessToken.token_type == "agent_runtime",
            models.AccessToken.bound_agent_id == agent_id,
            models.AccessToken.status == "active",
        )
        .order_by(models.AccessToken.id.desc())
        .all()
    )
    now = datetime.utcnow()
    return next(
        (
            row
            for row in rows
            if (not row.expires_at or row.expires_at >= now)
            and (not required_scope or required_scope in _load(row.scopes_json, []))
        ),
        None,
    )


def _client_issuance_token(db: Session, client_id: str) -> models.AccessToken | None:
    now = datetime.utcnow()
    rows = (
        db.query(models.AccessToken)
        .filter(
            models.AccessToken.token_type == "client",
            models.AccessToken.bound_client_id == client_id,
            models.AccessToken.status == "active",
            models.AccessToken.allow_agent_credential_issuance.is_(True),
        )
        .order_by(models.AccessToken.id.desc())
        .all()
    )
    return next((row for row in rows if not row.expires_at or row.expires_at >= now), None)


def _issue_agent_runtime_credential(
    db: Session,
    *,
    client_token: models.AccessToken,
    client_id: str,
    agent: models.ManagedAgent,
    model_name: str,
    allowed_mcp_gateways: list[str] | None = None,
    task: models.ClientTask,
    previous_credential_hash: str | None = None,
) -> tuple[str, models.AccessToken]:
    now = datetime.utcnow()
    payload = _load(task.payload_json, {})
    if "previous_credential_id" not in payload:
        if previous_credential_hash:
            previous = db.query(models.AccessToken).filter_by(token_hash=previous_credential_hash,
                token_type="agent_runtime", bound_agent_id=agent.agent_id, status="active").first()
        else:
            previous = _active_runtime_token(db, agent.agent_id, "model:chat")
        payload["previous_credential_id"] = previous.id if previous else None
    # Retain the immediate predecessor for the latest configuration's recovery.
    # Retries rotate only the newly issued attempt, not that predecessor.
    db.query(models.AccessToken).filter(
        models.AccessToken.token_type == "agent_runtime",
        models.AccessToken.bound_agent_id == agent.agent_id,
        models.AccessToken.issued_by_client_token_id == client_token.id,
        models.AccessToken.status == "active",
        models.AccessToken.id != (payload["previous_credential_id"] or -1),
    ).update(
        {
            "status": "revoked",
            "revoked_at": now,
            "revoked_by": f"client:{client_id}:rotation",
        },
        synchronize_session=False,
    )
    gateways = list(dict.fromkeys(str(item).strip() for item in (allowed_mcp_gateways or []) if str(item).strip()))
    scopes = list(_AUTO_AGENT_CREDENTIAL_SCOPES)
    if gateways:
        scopes.extend(["mcp:connect", "mcp:list-tools", "mcp:call-tools"])
    owner_id = client_token.user_id
    if not owner_id and client_token.created_by:
        owner = db.query(models.User).filter(models.User.username == client_token.created_by).first()
        owner_id = owner.id if owner else None
    plain = _new_token()
    model_policy = client_governance.policy_view(db, client_id)
    prompt_guard = model_policy["prompt_guard"]
    compression = model_policy["compression"]
    row = models.AccessToken(
        name=f"{agent.name} · {client_id} 自动运行凭证",
        token_type="agent_runtime",
        token_hash=_hash_token(plain),
        token_prefix=plain[:12],
        scopes_json=_dump(scopes),
        bound_agent_id=agent.agent_id,
        issued_by_client_token_id=client_token.id,
        user_id=owner_id,
        group_id=client_token.group_id,
        privacy_policy_id=client_token.privacy_policy_id,
        allowed_models_json=_dump([model_name]),
        allowed_mcp_gateways_json=_dump(gateways),
        allowed_ips_json=client_token.allowed_ips_json,
        expires_at=client_token.expires_at,
        max_body_kb=client_token.max_body_kb,
        max_concurrent_requests=client_token.max_concurrent_requests,
        prompt_guard_mode=prompt_guard["mode"],
        prompt_guard_llm_review=prompt_guard["llm_review"],
        enable_compression=compression["enabled"],
        compression_level=compression["level"],
        created_by=f"client:{client_id}",
    )
    db.add(row)
    db.flush()
    payload["issued_credential_id"] = row.id
    task.payload_json = _dump(payload)
    agent.runtime_token_id = row.id
    agent.default_model = model_name
    agent.updated_at = now
    db.add(
        models.ClientEvent(
            client_id=client_id,
            event_type="agent_credential_issued",
            agent_type=agent.channel,
            details_json=_dump(
                {
                    "managed_agent_id": agent.agent_id,
                    "token_prefix": row.token_prefix,
                    "allowed_models": [model_name],
                    "allowed_mcp_gateways": gateways,
                }
            ),
        )
    )
    db.commit()
    db.refresh(row)
    return plain, row


def _agent_model_names(db: Session, agent: models.ManagedAgent) -> list[str]:
    token = _active_runtime_token(db, agent.agent_id, "model:chat")
    if not token:
        return []
    allowed = [str(item) for item in _load(token.allowed_models_json, []) if str(item).strip()]
    query = db.query(models.ModelEndpoint).filter(models.ModelEndpoint.enabled.is_(True))
    if allowed:
        query = query.filter(models.ModelEndpoint.name.in_(allowed))
    return [row.name for row in query.order_by(models.ModelEndpoint.name.asc()).all()]


def _agent_gateway_names(db: Session, agent: models.ManagedAgent) -> list[str]:
    token = _active_runtime_token(db, agent.agent_id, "mcp:connect")
    if not token or not any(scope.startswith("mcp:") for scope in _load(token.scopes_json, [])):
        return []
    allowed = {str(item) for item in _load(token.allowed_mcp_gateways_json, [])}
    allowed.intersection_update(_load(agent.allowed_mcp_gateways_json, []))
    return [
        row.slug
        for row in db.query(models.McpGateway)
        .filter(models.McpGateway.status == "active")
        .order_by(models.McpGateway.slug.asc())
        .all()
        if row.slug in allowed
    ]


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


def _client_managed_agent_id(client_id: str, local_agent_id: str) -> str:
    source = f"{client_id}:{local_agent_id}"
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-") or "local-agent"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:10]
    return f"client-{slug[:100]}-{digest}"


def _ensure_client_managed_agent(
    db: Session,
    *,
    client: models.ManagedClient,
    client_agent: models.ClientAgent,
    token: models.AccessToken,
    model_name: str,
) -> models.ManagedAgent:
    local_agent_id = _local_agent_id(client_agent.local_agent_id, client_agent.agent_type)
    agent_id = _client_managed_agent_id(client.client_id, local_agent_id)
    existing = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == agent_id).first()
    if existing:
        linked_client = db.query(models.ClientAgent.client_id).filter(
            models.ClientAgent.managed_agent_id == agent_id
        ).first()
        if (
            existing.origin_type != "client_discovery"
            or _agent_kind(existing.channel) != _agent_kind(client_agent.agent_type)
            or (linked_client and linked_client[0] != client.client_id)
            or not _token_can_use_agent(db, token, existing)
        ):
            raise ApiError(
                409,
                "client.auto_agent_identity_conflict",
                "本机 Agent 的自动运行身份与现有记录冲突",
                "The automatic runtime identity for this local Agent conflicts with an existing record",
            )
        if existing.status != "active":
            raise ApiError(
                409,
                "client.auto_agent_identity_disabled",
                "本机 Agent 的自动运行身份已被停用，请先在管理台启用",
                "The automatic runtime identity for this local Agent is disabled",
            )
        existing.default_model = model_name
        existing.updated_at = datetime.utcnow()
        return existing
    label = _MODEL_CONFIG_AGENT_LABELS.get(client_agent.agent_type, client_agent.agent_type)
    owner = token.created_by or client.registered_by
    require_license()
    row = models.ManagedAgent(
        registration_source="client_discovery",
        agent_id=agent_id,
        name=f"{client.name} · {label}"[:128],
        department_group_id=token.group_id,
        owner=owner,
        description=f"由客户端 {client.name} ({client.client_id}) 为本机 {label} 自动创建的运行身份。",
        channel=label,
        status="active",
        default_model=model_name,
        origin_type="client_discovery",
        skill_names_json="[]",
        prompt_names_json="[]",
        created_by=owner,
    )
    db.add(row)
    db.flush()
    db.add(
        models.ClientEvent(
            client_id=client.client_id,
            event_type="managed_agent_auto_created",
            agent_type=client_agent.agent_type,
            details_json=_dump(
                {
                    "local_agent_id": local_agent_id,
                    "managed_agent_id": row.agent_id,
                    "source": "model_switch",
                }
            ),
        )
    )
    return row


def _ensure_inventory_agent_identity(
    db: Session,
    *,
    client: models.ManagedClient,
    client_agent: models.ClientAgent,
    owner: str | None,
    group_id: int | None = None,
    source: str = "inventory",
) -> models.ManagedAgent:
    """Create the stable internal identity for a Client-discovered Agent.

    The identity is infrastructure for policy, credentials and audit. It is not
    a user-managed association to a separately created platform Agent.
    """
    local_agent_id = _local_agent_id(client_agent.local_agent_id, client_agent.agent_type)
    agent_id = _client_managed_agent_id(client.client_id, local_agent_id)
    existing = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == agent_id).first()
    if existing:
        linked_client = db.query(models.ClientAgent.client_id).filter(
            models.ClientAgent.managed_agent_id == agent_id
        ).first()
        if (
            existing.origin_type != "client_discovery"
            or _agent_kind(existing.channel) != _agent_kind(client_agent.agent_type)
            or (linked_client and linked_client[0] != client.client_id)
        ):
            raise ApiError(
                409,
                "client.auto_agent_identity_conflict",
                "本机 Agent 的自动运行身份与现有记录冲突",
                "The automatic runtime identity for this local Agent conflicts with an existing record",
            )
        return existing
    label = _MODEL_CONFIG_AGENT_LABELS.get(client_agent.agent_type, client_agent.agent_type)
    row = models.ManagedAgent(
        registration_source="client_discovery",
        agent_id=agent_id,
        name=f"{client.name} · {label}"[:128],
        department_group_id=group_id,
        owner=owner or client.registered_by,
        description=f"由客户端 {client.name} ({client.client_id}) 自动登记的本机 {label}。",
        channel=label,
        status="active",
        default_model=client_agent.applied_model or client_agent.desired_model,
        origin_type="client_discovery",
        skill_names_json="[]",
        prompt_names_json="[]",
        created_by=owner or client.registered_by,
    )
    db.add(row)
    db.flush()
    db.add(
        models.ClientEvent(
            client_id=client.client_id,
            event_type="managed_agent_auto_created",
            agent_type=client_agent.agent_type,
            details_json=_dump(
                {
                    "local_agent_id": local_agent_id,
                    "managed_agent_id": row.agent_id,
                    "source": source,
                }
            ),
        )
    )
    return row


def ensure_client_inventory_identities(
    db: Session,
    client: models.ManagedClient,
    *,
    owner: str | None,
    group_id: int | None = None,
    source: str = "inventory",
) -> int:
    created_or_bound = 0
    for client_agent in db.query(models.ClientAgent).filter(models.ClientAgent.client_id == client.client_id).all():
        discovery_id = _client_managed_agent_id(
            client.client_id, _local_agent_id(client_agent.local_agent_id, client_agent.agent_type)
        )
        identity_exists = db.query(models.ManagedAgent.id).filter_by(agent_id=discovery_id).first() is not None
        if not identity_exists:
            try:
                require_license()
            except LicenseError:
                continue
        identity = _ensure_inventory_agent_identity(
            db,
            client=client,
            client_agent=client_agent,
            owner=owner,
            group_id=group_id,
            source=source,
        )
        # Inventory identity and an existing runtime credential binding have
        # separate lifecycles. Keep the latter while registering local assets.
        needs_binding = not client_agent.managed_agent_id
        if needs_binding:
            client_agent.managed_agent_id = identity.agent_id
        client_agent.takeover_status = "managed"
        if not identity_exists or needs_binding:
            created_or_bound += 1
    return created_or_bound


def backfill_client_inventory_identities(db: Session) -> int:
    changed = 0
    for client in db.query(models.ManagedClient).all():
        changed += ensure_client_inventory_identities(
            db,
            client,
            owner=client.registered_by,
            source="migration",
        )
    return changed


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


def _available_skill_item(entry) -> dict:
    display_name, _description = _skill_display_metadata(
        entry.name,
        getattr(entry, "description", "") or "",
        Path(entry.skill_path),
    )
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
    return item


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


def _client_update_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for channel in ("stable", "preview"):
        try:
            manifest = _client_update_manifest(channel)
        except HTTPException:
            continue
        version = str((manifest or {}).get("version") or "").strip()
        if re.fullmatch(r"\d+(?:\.\d+){2,3}", version):
            versions[channel] = version
    return versions


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
        and (
            allowed_refs is None
            or entry.skill_id in allowed_refs
            or (getattr(entry, "family_id", None) or "") in allowed_refs
            or entry.name in allowed_refs
        )
    ]
    if local_skill.version_id:
        exact_version = next(
            (entry for entry in candidates if entry.skill_id == local_skill.version_id),
            None,
        )
        if exact_version is not None and local_skill.signature and exact_version.skill_path and _cached_skill_signature(exact_version.skill_path, signature_cache) == local_skill.signature:
            return exact_version

    matching_content = []
    for candidate in candidates:
        if not candidate.skill_path or not local_skill.signature:
            continue
        if _cached_skill_signature(candidate.skill_path, signature_cache) == local_skill.signature:
            matching_content.append(candidate)

    def newest_version(entries):
        return max(entries, key=lambda entry: int(getattr(entry, "version_no", 0) or 0))

    if matching_content:
        trusted_matches = [
            entry
            for entry in matching_content
            if entry.status in (SkillStatus.APPROVED, SkillStatus.DEPLOYED)
        ]
        # Multiple immutable versions may have the same governed content when
        # they differ only by ignored metadata such as .DS_Store. In that case
        # the matching approved version is the valid trust anchor.
        return newest_version(trusted_matches or matching_content)

    trusted_candidates = [
        entry
        for entry in candidates
        if entry.status in (SkillStatus.APPROVED, SkillStatus.DEPLOYED)
    ]
    if trusted_candidates:
        return newest_version(trusted_candidates)
    return candidates[0] if candidates else manager.get_skill(local_skill.name)


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


def _replace_recovery_inventory(db: Session, client_id: str, records) -> None:
    if records is None:
        return
    db.query(models.ClientRecoveryRecord).filter_by(client_id=client_id).delete()
    unique = {item.id: item for item in records}
    for item in unique.values():
        db.add(models.ClientRecoveryRecord(client_id=client_id, record_id=item.id, details_json=_dump(item.model_dump())))
    db.flush()


def _replace_inventory(db: Session, client_id: str, agents: list[schemas.ClientAgentInventory]) -> None:
    existing = {
        _local_agent_id(row.local_agent_id, row.agent_type): row
        for row in db.query(models.ClientAgent).filter(models.ClientAgent.client_id == client_id).all()
    }
    db.query(models.ClientSkillInstall).filter(models.ClientSkillInstall.client_id == client_id).delete()
    db.query(models.ClientAgent).filter(models.ClientAgent.client_id == client_id).delete()
    now = datetime.utcnow()
    for agent in agents:
        local_agent_id = _local_agent_id(agent.local_agent_id, agent.agent_type)
        previous = existing.get(local_agent_id)
        managed_agent_id = agent.managed_agent_id or (previous.managed_agent_id if previous else None)
        db.add(
            models.ClientAgent(
                client_id=client_id,
                local_agent_id=local_agent_id,
                agent_type=agent.agent_type,
                managed_agent_id=managed_agent_id,
                agent_version=agent.version,
                install_path=agent.install_path,
                skills_path=agent.skills_path,
                skill_management_supported=agent.skill_management_supported,
                capabilities_json=_dump(inventory_capabilities(agent.capabilities, agent.asset_inventory)),
                desired_model=previous.desired_model if previous else None,
                applied_model=previous.applied_model if previous else None,
                model_config_status=previous.model_config_status if previous else "not_configured",
                model_config_error=previous.model_config_error if previous else None,
                model_config_updated_at=previous.model_config_updated_at if previous else None,
                takeover_status="managed" if managed_agent_id else "discovered",
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
                    governance_json=(
                        _dump(skill.governance.model_dump(mode="json"))
                        if skill.governance and skill.governance.signature == skill.signature
                        else None
                    ),
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


def _client_related(db: Session, rows) -> dict:
    result = {}
    ids = [row.client_id for row in rows]
    for offset in range(0, len(ids), 200):
        part = ids[offset:offset + 200]
        policies = client_governance.policy_views(db, part)
        group = {cid: dict(agents=[], skills=[], recovery=[], classification=policies[cid], issues=0, alerts=0)
                 for cid in part}
        for model, key in ((models.ClientAgent, 'agents'), (models.ClientSkillInstall, 'skills'),
                           (models.ClientRecoveryRecord, 'recovery')):
            for item in db.query(model).filter(model.client_id.in_(part)):
                group[item.client_id][key].append(item)
        event = models.ClientEvent
        latest = db.query(func.max(event.id).label('event_id')).filter(
            event.client_id.in_(part), event.skill_name.is_not(None)).group_by(
                event.client_id, event.agent_type, event.skill_name).subquery()
        for cid, count in db.query(event.client_id, func.count(event.id)).join(
                latest, event.id == latest.c.event_id).filter(event.event_type.in_(
                    ('unmanaged_skill_found', 'skill_modified', 'skill_blocked', 'skill_quarantined'))
                ).group_by(event.client_id):
            group[cid]['issues'] = count
        for cid, count in db.query(event.client_id, func.count(event.id)).filter(
                event.client_id.in_(part), event.event_type == 'aidr_skill_alert',
                func.json_extract(event.details_json, '$.active') == 1).group_by(event.client_id):
            group[cid]['alerts'] = count
        result.update(group)
    return result


def _client_response(db: Session, row: models.ManagedClient, *, related=None) -> dict:
    data = related if related is not None else _client_related(db, [row])[row.client_id]
    agents, skills, classification = data['agents'], data['skills'], data['classification']
    issue_count = data['issues']
    if classification["enabled"] and classification["supported"]:
        affected_paths = set()
        for skill in skills:
            observation = _load(skill.governance_json, {})
            if not observation or observation.get("signature") != skill.signature:
                continue
            if (observation.get("trigger") in client_governance.ACTIONS and observation.get("action") != "record_only") or observation.get("action_status") == "failed":
                affected_paths.add(skill.skill_path)
        issue_count = len(affected_paths)
    issue_count += data['alerts']
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
        "classification": classification,
        "status": "online" if online else "offline",
        "last_seen_at": row.last_seen_at,
        "registered_by": row.registered_by,
        "device_user": row.device_user,
        "assignment_note": row.assignment_note,
        "created_at": row.created_at,
        "issue_count": issue_count,
        "recovery": [_load(item.details_json, {}) for item in data['recovery']],
        "model_routing": classification["model_routing"],
        "agents": [
            {
                "local_agent_id": _local_agent_id(agent.local_agent_id, agent.agent_type),
                "agent_type": agent.agent_type,
                "managed_agent_id": agent.managed_agent_id,
                "version": agent.agent_version,
                "install_path": agent.install_path,
                "skills_path": agent.skills_path,
                "skill_management_supported": agent.skill_management_supported,
                "asset_inventory": asset_inventory(_load(agent.capabilities_json, {})),
                "capabilities": {**_load(agent.capabilities_json, {}), **({"model_config_contract": contract_for_version(agent.agent_type, agent.agent_version)} if agent.agent_type in MODEL_ADAPTERS else {})},
                "desired_model": agent.desired_model,
                "applied_model": agent.applied_model,
                "model_config_status": agent.model_config_status,
                "model_config_error": agent.model_config_error,
                "model_config_updated_at": agent.model_config_updated_at,
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
                        "governance": _load(skill.governance_json, None),
                    }
                    for skill in skills
                    if skill.agent_type == agent.agent_type
                ],
            }
            for agent in agents
        ],
    }


def _client_policy_response(db: Session, row: models.ManagedClient) -> dict:
    classification = client_governance.policy_view(db, row.client_id)
    observation = db.get(runtime_governance.Observation, row.client_id)
    runtime_protocol = json.loads(observation.report_json).get("protocol", 0) if observation else 0
    runtime_governance.check_product_policy(classification, runtime_protocol)
    classification["runtime_governance"] = runtime_governance.client_target(
        classification["runtime_governance"], json.loads(observation.report_json) if observation else None)
    if classification["incompatible_rules"]:
        raise ApiError(409, "client.policy_capability_required", "当前客户端不支持生效策略中的动作，请升级客户端", "Upgrade this client to execute the active policy actions")
    if classification["protocol"] == 1:
        classification["rules"] = {key: value for key, value in classification["rules"].items() if not key.endswith("scan_rejected")}
    bindings = db.query(models.ClientAgent).filter(models.ClientAgent.client_id == row.client_id).all()
    profiles = []
    for binding in bindings:
        if not binding.managed_agent_id:
            continue
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == binding.managed_agent_id).first()
        if not agent or agent.status != "active":
            continue
        profiles.append(
            {
                "local_agent_id": _local_agent_id(binding.local_agent_id, binding.agent_type),
                "agent_type": binding.agent_type,
                "managed_agent_id": agent.agent_id,
                "default_model": agent.default_model,
                "allowed_models": _agent_model_names(db, agent),
                "allowed_mcp_gateways": _agent_gateway_names(db, agent),
                "auto_apply_supported": (
                    binding.agent_type in _MODEL_CONFIG_AGENT_TYPES
                    and bool(_load(binding.capabilities_json, {}).get("model_config_auto_apply"))
                ),
            }
        )
    return {
        "mode": row.policy_mode,
        "agent_discovery": {key: value for key, value in client_discovery.view(db, row).items() if key in {"version", "agents"}},
        "classification": classification,
        "governance_mode": row.governance_mode,
        "light_scan_seconds": 300,
        "full_scan_seconds": 1800,
        "release_public_key": public_key_base64(),
        "ordinary_events_protocol": 1,
        "agent_bindings": {
            binding.agent_type: binding.managed_agent_id
            for binding in bindings
            if binding.managed_agent_id
        },
        "agent_profiles": profiles,
    }


def _external_catalog_response(
    db: Session,
    *,
    client: models.ManagedClient,
    client_agent: models.ClientAgent,
    managed_agent: models.ManagedAgent,
) -> dict:
    routing = client_governance.policy_view(db, client.client_id)["model_routing"]
    if not routing.get("external_gateway_enabled"):
        raise ApiError(403, "client.external_gateway_disabled", "平台策略未允许使用外部 AI 网关", "The platform policy does not allow external AI gateways")
    gateway = db.get(models.ExternalAIGateway, routing.get("external_gateway_id"))
    if not gateway or not gateway.enabled:
        raise ApiError(409, "client.external_gateway_unavailable", "外部 AI 网关不存在或未启用", "The external AI gateway is missing or disabled")
    binding = db.query(models.ExternalGatewayAgentBinding).filter_by(
        gateway_id=gateway.id, managed_agent_id=managed_agent.agent_id
    ).first()
    if not binding and not routing.get("auto_register_agent", True):
        raise ApiError(409, "client.external_agent_registration_required", "外部 Agent 尚未注册", "The external Agent has not been registered")
    binding = ensure_binding(db, gateway, managed_agent, client_id=client.client_id)
    catalog = binding_models(db, gateway, binding)
    db.commit()
    return {
        "source": "external_gateway",
        "gateway": {"id": gateway.id, "name": gateway.name, "model_base_url": gateway.model_base_url},
        "binding": {
            "id": binding.id,
            "external_agent_id": binding.external_agent_id,
            "key_id": binding.key_id,
            "status": binding.status,
            "models_refreshed_at": binding.models_refreshed_at,
        },
        "models": catalog,
        "auth_scheme": "bearer",
        "agent": {
            "agent_type": client_agent.agent_type,
            "local_agent_id": _local_agent_id(client_agent.local_agent_id, client_agent.agent_type),
            "managed_agent_id": managed_agent.agent_id,
        },
    }


def _catalog_target(
    db: Session,
    client: models.ManagedClient,
    body: schemas.ClientExternalModelCatalogRequest,
) -> tuple[models.ClientAgent, models.ManagedAgent | None]:
    local_agent_id = _local_agent_id(body.local_agent_id, body.agent_type.strip())
    client_agent = db.query(models.ClientAgent).filter_by(
        client_id=client.client_id, local_agent_id=local_agent_id, agent_type=body.agent_type.strip()
    ).first()
    if not client_agent or not _load(client_agent.capabilities_json, {}).get("model_config_auto_apply"):
        raise ApiError(400, "client.model_config_agent_unsupported", "客户端未发现支持模型切换的目标 Agent", "The Client did not discover a target Agent that supports model switching")
    requested = str(body.managed_agent_id or "").strip()
    if client_agent.managed_agent_id and requested not in {"", client_agent.managed_agent_id}:
        raise ApiError(409, "client.agent_identity_mismatch", "本机 Agent 身份与请求不一致", "The local Agent identity does not match the request")
    managed_id = client_agent.managed_agent_id
    managed_agent = db.query(models.ManagedAgent).filter_by(agent_id=managed_id, status="active").first() if managed_id else None
    return client_agent, managed_agent


def _task_history(db: Session, client_id: str, limit: int = 100, rows=None) -> list[dict]:
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
        for task in (rows if rows is not None else (
            db.query(models.ClientTask)
            .filter(models.ClientTask.client_id == client_id)
            .order_by(models.ClientTask.id.desc())
            .limit(limit)
            .all()
        ))
    ]


def _update_model_config_state(
    db: Session,
    client_id: str,
    payload: dict,
    status: str,
    error: str | None = None,
) -> None:
    local_agent_id = _local_agent_id(payload.get("local_agent_id"), str(payload.get("agent_type") or ""))
    client_agent = (
        db.query(models.ClientAgent)
        .filter(
            models.ClientAgent.client_id == client_id,
            models.ClientAgent.local_agent_id == local_agent_id,
        )
        .first()
    )
    if not client_agent:
        return
    client_agent.model_config_status = status
    client_agent.model_config_error = error
    client_agent.model_config_updated_at = datetime.utcnow()
    if status in {"applied", "pending_restart"}:
        client_agent.applied_model = str(payload.get("model") or "") or None


_GOVERNANCE_ACTION_RECORD_TYPES = {
    "quarantine": "skill_quarantined",
    "uninstall": "skill_removed",
    "restore_backup": "skill_repaired",
    "restore_quarantine": "skill_quarantine_restored",
    "restore_trusted": "skill_repaired",
}


def _event_record_type(event_type: str, details: dict) -> str:
    if event_type == "skill_governance_action":
        return _GOVERNANCE_ACTION_RECORD_TYPES.get(str(details.get("action") or ""), event_type)
    return event_type


def _event_record_type_expression():
    action = func.json_extract(models.ClientEvent.details_json, "$.action")
    return case(
        *(
            (
                and_(
                    models.ClientEvent.event_type == "skill_governance_action",
                    action == action_name,
                ),
                record_type,
            )
            for action_name, record_type in _GOVERNANCE_ACTION_RECORD_TYPES.items()
        ),
        else_=models.ClientEvent.event_type,
    )


def _event_history(db: Session, client_id: str, limit: int = 100, rows=None) -> list[dict]:
    events = rows if rows is not None else (
        db.query(models.ClientEvent)
        .filter(models.ClientEvent.client_id == client_id)
        .filter(models.ClientEvent.event_type.notin_(("client_registered", "takeover_completed")))
        .order_by(client_event_records.expressions()[2].desc(), models.ClientEvent.id.desc())
        .limit(limit)
        .all()
    )
    linked = client_event_records.usages(db, client_id, events)
    result = []
    for event in events:
        details = _load(event.details_json, {})
        usage_id = str(details.get('usage_id', ''))
        result.append({
            "id": event.id,
            "event_type": event.event_type,
            "record_type": _event_record_type(event.event_type, details),
            "agent_type": event.agent_type,
            "skill_name": event.skill_name,
            "details": details,
            "created_at": event.created_at,
            "last_seen_at": event.last_seen_at or event.created_at,
            "observation_count": event.observation_count,
            "presentation": client_event_records.present(event, details, linked.get(int(usage_id)) if usage_id.isdigit() else None),
        })
    return result


@router.post("/register")
def register_client(
    body: schemas.ClientRegisterRequest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:register", authorization, request, db)
    _bind_client(token, body.client_id, db)
    # Serialize count and registration in the same transaction, even for an empty table.
    db.query(models.ManagedClient).filter(models.ManagedClient.id == -1).update({"status": models.ManagedClient.status}, synchronize_session=False)
    row = db.query(models.ManagedClient).filter(models.ManagedClient.client_id == body.client_id).first()
    is_new = row is None
    if is_new:
        entitlement = require_license()
        if db.query(models.ManagedClient).count() >= entitlement["limits"]["clients"]:
            raise LicenseError("client_limit")
        row = models.ManagedClient(client_id=body.client_id, registered_by=token.created_by,
                                   device_user=token.device_user, assignment_note=token.assignment_note)
        db.add(row)
    row.name = body.name.strip() or body.hostname
    row.hostname = body.hostname
    row.os = body.os
    row.arch = body.arch
    row.client_version = body.client_version
    row.status = "online"
    row.last_seen_at = datetime.utcnow()
    _replace_inventory(db, body.client_id, body.agents)
    _replace_recovery_inventory(db, body.client_id, body.recovery)
    client_governance.record_protocol(db, body.client_id, body.governance_protocol, is_new=is_new)
    ensure_client_inventory_identities(db, row, owner=token.created_by, group_id=token.group_id)
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
    client_governance.record_protocol(db, client_id, body.governance_protocol)
    client_governance.record_desktop_menus(db, client_id, body.desktop_menu_protocol, body.applied_desktop_menu_visibility)
    if body.runtime_governance is not None:
        runtime_governance.record_enrollment(db, client_id, body.runtime_governance)
        runtime_governance.record(db, client_id, body.runtime_governance)
        runtime_governance.coordinate(db, row, body.runtime_governance)
    else:
        db.query(runtime_governance.Observation).filter_by(client_id=client_id).update({"supports_tasks": False}, synchronize_session=False)
    db.commit()
    return {"ok": True, "last_seen_at": row.last_seen_at, "policy": _client_policy_response(db, row)}


@router.get("/discovery-config")
def get_discovery_config(client_id: str | None = None, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    return client_discovery.view(db, _client_or_404(db, client_id) if client_id else None)


@router.put("/discovery-config")
def update_discovery_config(body: client_discovery.CatalogChange, client_id: str | None = None, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    client = _client_or_404(db, client_id) if client_id else None
    clients = [client] if client else db.query(models.ManagedClient).all()
    previous = {row.client_id: client_discovery.view(db, row)['version'] for row in clients}
    result = client_discovery.save(db, body, client)
    for row in clients:
        effective = client_discovery.view(db, row)
        if effective['version'] != previous[row.client_id]:
            db.add(models.ClientTask(
                client_id=row.client_id,
                task_type="sync_policy",
                payload_json=_dump({"agent_discovery_version": effective["version"]}),
            ))
    _operation(db, current_user, "client_discovery_updated", client_id or "clients", json.dumps(result, ensure_ascii=False))
    db.commit()
    return result


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


@router.get("/{client_id}/history")
def get_client_history(
    client_id: str, request: Request,
    kind: str = Query("events", pattern="^(events|tasks)$"),
    page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100),
    keyword: str = Query("", max_length=200), agent: str = Query("", max_length=128),
    record_type: str = Query("", max_length=128), status: str = Query("", max_length=64),
    category: str = Query("", max_length=32),
    days: int = Query(0, ge=0, le=365),
    authorization: str | None = Header(None), db: Session = Depends(get_db),
):
    token = _runtime_token("client:read-policy", authorization, request, db)
    _bind_client(token, client_id, db)
    _client_or_404(db, client_id)
    return _history_page(db, client_id, kind, page, page_size, keyword, agent, record_type, status, days, category)


@router.get("/{client_id}/event-records")
def get_event_records(client_id: str, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=100),
                      keyword: str = Query('', max_length=200), agent: str = Query('', max_length=128),
                      category: str = Query('', max_length=32), status: str = Query('', max_length=64),
                      days: int = Query(0, ge=0, le=365), db: Session = Depends(get_db),
                      user=Depends(auth.get_current_admin_user)):
    _ensure_visible(_client_or_404(db, client_id), user)
    return _history_page(db, client_id, 'events', page, page_size, keyword, agent, '', status, days, category)


def _history_page(db, client_id, kind, page, page_size, keyword, agent, record_type, status, days, category=''):
    is_task = kind == "tasks"
    model = models.ClientTask if is_task else models.ClientEvent
    query = db.query(model).filter(model.client_id == client_id)
    if not is_task:
        query = query.filter(model.event_type.notin_(("client_registered", "takeover_completed")))
    if is_task:
        action = func.json_extract(model.payload_json, "$.action")
        type_column = case((and_(model.task_type == 'aidr_plugin_action', action.in_(['install', 'upgrade', 'inspect', 'enable', 'disable', 'reconcile'])), model.task_type + ':' + action), else_=model.task_type)
        task_agent = case((model.task_type == 'aidr_plugin_action', func.json_extract(model.payload_json, '$.agent')), else_=func.json_extract(model.payload_json, '$.agent_type'))
        agent_column = case((task_agent == 'claude', 'claude-code'), else_=task_agent)
        hosts = func.json_each(model.payload_json, '$.target.hosts').table_valued('value')
        def targets_host(value):
            return and_(model.task_type == 'aidr_plugin_action', action == 'reconcile',
                        db.query(hosts.c.value).filter(hosts.c.value == value).exists())
    else:
        type_column = _event_record_type_expression()
        agent_column = model.agent_type
    event_category, event_state, event_time = client_event_records.expressions()
    timestamp = func.coalesce(model.finished_at, model.started_at, model.created_at) if is_task else event_time
    types = [value for (value,) in query.with_entities(type_column).distinct().all() if value]
    agents = [value for (value,) in query.with_entities(agent_column).distinct().all() if value]
    if is_task:
        for host, label in [('codex', 'codex'), ('claude', 'claude-code')]:
            if label not in agents and query.filter(targets_host(host)).first():
                agents.append(label)
    if keyword.strip():
        columns = [type_column, model.payload_json, model.error] if is_task else [type_column, model.skill_name, model.details_json]
        query = query.filter(or_(*(column.contains(keyword.strip(), autoescape=True) for column in columns)))
    if agent:
        query = query.filter(or_(agent_column == agent, targets_host('claude' if agent == 'claude-code' else agent)) if is_task else agent_column == agent)
    if record_type:
        query = query.filter(model.task_type == record_type if is_task and record_type == 'aidr_plugin_action' else type_column == record_type)
    if status and is_task:
        query = query.filter(model.status == status)
    elif status:
        query = query.filter(event_state == status)
    if category and not is_task:
        query = query.filter(event_category == category)
    if days:
        query = query.filter(timestamp >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days))
    total = query.count()
    page = min(page, max(1, (total + page_size - 1) // page_size))
    rows = query.order_by(timestamp.desc(), model.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": (_task_history if is_task else _event_history)(db, client_id, rows=rows),
            "total": total, "page": page, "page_size": page_size, "types": sorted(types), "agents": sorted(agents),
            "categories": client_event_records.CATEGORIES, "states": client_event_records.STATES}


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
    result["manual_skill_actions_allowed"] = "client:request-skill-actions" in _load(token.scopes_json, [])
    can_configure_models = bool(token.allow_agent_credential_issuance)
    allowed_model_names = {
        str(item).strip()
        for item in _load(token.allowed_models_json, [])
        if str(item).strip()
    }
    model_query = (
        db.query(models.ModelEndpoint, models.ModelProvider)
        .join(models.ModelProvider, models.ModelProvider.id == models.ModelEndpoint.provider_id)
        .filter(
            models.ModelEndpoint.enabled.is_(True),
            models.ModelProvider.enabled.is_(True),
        )
    )
    if allowed_model_names:
        model_query = model_query.filter(models.ModelEndpoint.name.in_(allowed_model_names))
    routing = client_governance.policy_view(db, client_id)["model_routing"]
    external_gateway = (
        db.get(models.ExternalAIGateway, routing.get("external_gateway_id"))
        if routing.get("external_gateway_enabled") and routing.get("external_gateway_id")
        else None
    )
    bound_managed_agent_ids = [
        item.managed_agent_id
        for item in db.query(models.ClientAgent).filter_by(client_id=client_id).all()
        if item.managed_agent_id
    ]
    result["model_configuration"] = {
        "gateway_url": settings.MODEL_GATEWAY_PUBLIC_URL,
        "adapters": MODEL_ADAPTERS,
        "can_configure_models": can_configure_models,
        "can_export_manual_credentials": can_configure_models and bool(token.allow_manual_credential_export),
        "allowed_model_scope": "selected" if allowed_model_names else "all",
        "automatic_agent_credential_scopes": list(_AUTO_AGENT_CREDENTIAL_SCOPES),
        "models": [
            {
                "id": model.id,
                "name": model.name,
                "display_name": model.display_name,
                "upstream_name": model.upstream_name or model.name,
                "provider_id": provider.id,
                "provider_name": provider.name,
                "context_window": model.context_window,
                "max_output_tokens": model.max_output_tokens,
                "is_default": model.is_default,
            }
            for model, provider in (
                model_query.order_by(models.ModelEndpoint.is_default.desc(), models.ModelEndpoint.name.asc()).all()
                if can_configure_models
                else []
            )
        ],
        "model_routing": routing,
        "external_gateway": (
            {
                "id": external_gateway.id,
                "name": external_gateway.name,
                "model_base_url": external_gateway.model_base_url,
            }
            if external_gateway and external_gateway.enabled
            else None
        ),
        "external_catalogs": [
            {
                "gateway_id": binding.gateway_id,
                "gateway_name": external_gateway.name if external_gateway and binding.gateway_id == external_gateway.id else None,
                "managed_agent_id": binding.managed_agent_id,
                "external_agent_id": binding.external_agent_id,
                "key_id": binding.key_id,
                "status": binding.status,
                "models": _load(binding.available_models_json, []),
                "models_refreshed_at": binding.models_refreshed_at,
            }
            for binding in db.query(models.ExternalGatewayAgentBinding)
            .filter(
                models.ExternalGatewayAgentBinding.gateway_id == routing.get("external_gateway_id"),
                models.ExternalGatewayAgentBinding.managed_agent_id.in_(
                    bound_managed_agent_ids
                )
            )
            .order_by(models.ExternalGatewayAgentBinding.id)
            .all()
        ] if routing.get("external_gateway_enabled") and routing.get("client_select_model", True) else [],
    }
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
    result["tasks"] = _task_history(db, client_id, 20)
    result["events"] = _event_history(db, client_id, 50)
    return result


def _manual_model_target(db, client_id, body, request, authorization):
    token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    if not token.allow_agent_credential_issuance or not token.allow_manual_credential_export:
        raise ApiError(403, "client.manual_credential_permission", "当前客户端未获准领取并复制 Agent 凭证", "This Client is not authorized to retrieve and copy Agent credentials")
    _lock_model_task_agent(db, client_id, body.local_agent_id)
    local = db.query(models.ClientAgent).filter_by(client_id=client_id, local_agent_id=body.local_agent_id, agent_type=body.agent_type).first()
    if not local:
        raise ApiError(404, "client.agent_not_found", "未找到当前客户端的目标 Agent", "The target Agent was not found on this Client")
    if not local.managed_agent_id:
        identity = _ensure_inventory_agent_identity(db, client=client, client_agent=local, owner=token.created_by, group_id=token.group_id, source="manual_model")
        local.managed_agent_id = identity.agent_id
        db.flush()
    agent = db.query(models.ManagedAgent).filter_by(agent_id=local.managed_agent_id, status="active").first()
    if not agent or not _token_can_use_agent(db, token, agent):
        raise ApiError(403, "client.manual_agent_unavailable", "目标 Agent 未启用或无权访问", "The target Agent is disabled or inaccessible")
    routing = client_governance.policy_view(db, client_id)["model_routing"]
    if routing.get("external_gateway_enabled") and not routing.get("client_select_model", True):
        raise ApiError(403, "client.external_model_selection_disabled", "平台策略未允许客户端自主选择外部模型", "Client-side external model selection is disabled")
    return token, client, local, agent, routing


def _manual_handoff(db, client_id, token_id, local_id, source):
    rows = db.query(models.ClientTask).filter_by(client_id=client_id, task_type="manual_model_credential").order_by(models.ClientTask.id.desc()).all()
    for row in rows:
        value = _load(row.payload_json, {})
        if value.get("issuer_id") != token_id or value.get("local_agent_id") != local_id or value.get("source") != source:
            continue
        credential = db.get(models.AccessToken, value.get("credential_id")) if value.get("credential_id") else None
        if credential and (credential.status != "active" or (credential.expires_at and credential.expires_at < datetime.utcnow())):
            continue
        return value
    return None


@router.post("/{client_id}/manual-model/options")
def manual_model_options(client_id: str, body: schemas.ClientExternalModelCatalogRequest, request: Request,
                         authorization: str | None = Header(None), db: Session = Depends(get_db)):
    token, client, local, agent, routing = _manual_model_target(db, client_id, body, request, authorization)
    if routing.get("external_gateway_enabled"):
        result = _external_catalog_response(db, client=client, client_agent=local, managed_agent=agent)
        result["gateway_url"] = result["gateway"]["model_base_url"]
        result["models"] = [{"name": item["id"], "display_name": item.get("name") or item["id"]} for item in result["models"]]
    else:
        allowed = _load(token.allowed_models_json, [])
        query = db.query(models.ModelEndpoint).join(models.ModelProvider).filter(models.ModelEndpoint.enabled.is_(True), models.ModelProvider.enabled.is_(True))
        if allowed:
            query = query.filter(models.ModelEndpoint.name.in_(allowed))
        result = {"source": "internal", "gateway_url": settings.MODEL_GATEWAY_PUBLIC_URL,
                  "models": [{"name": item.name, "display_name": item.display_name or item.name} for item in query.order_by(models.ModelEndpoint.name).all()]}
    result["handoff"] = _manual_handoff(db, client_id, token.id, local.local_agent_id, result["source"])
    db.commit()
    return result


@router.post("/{client_id}/manual-model/credential")
def manual_model_credential(client_id: str, body: schemas.ClientManualModelCredentialRequest, request: Request, response: Response,
                            authorization: str | None = Header(None), db: Session = Depends(get_db)):
    token, client, local, agent, routing = _manual_model_target(db, client_id, body, request, authorization)
    source = "external_gateway" if routing.get("external_gateway_enabled") else "internal"
    if source != body.source:
        raise ApiError(409, "client.manual_route_changed", "网关策略已变化，请重新读取接入信息", "Gateway policy changed; reload connection information")
    key = hashlib.sha256(f"manual-model:{client_id}:{token.id}:{body.request_id}".encode()).hexdigest()
    existing = db.query(models.ClientTask).filter_by(request_key=key).first()
    if existing:
        value = _load(existing.payload_json, {})
        if any(value.get(field) != getattr(body, field) for field in ("local_agent_id", "agent_type", "model", "source", "protocol")):
            raise ApiError(409, "client.manual_request_conflict", "本次申请的目标已变化，请重新打开配置引导", "The request target changed; reopen the guide")
        allowed = _load(token.allowed_models_json, [])
        if source == "internal":
            issued = db.get(models.AccessToken, value.get("credential_id"))
            enabled = db.query(models.ModelEndpoint).join(models.ModelProvider).filter(models.ModelEndpoint.name == body.model, models.ModelEndpoint.enabled.is_(True), models.ModelProvider.enabled.is_(True)).first()
            if not issued or issued.status != "active" or (issued.expires_at and issued.expires_at < datetime.utcnow()) or not enabled or (allowed and body.model not in allowed):
                raise ApiError(403, "client.manual_credential_unavailable", "本次领取的凭证已失效或模型授权已变化", "The credential expired or its model authorization changed")
        else:
            gateway = db.get(models.ExternalAIGateway, routing.get("external_gateway_id"))
            binding = db.query(models.ExternalGatewayAgentBinding).filter_by(gateway_id=routing.get("external_gateway_id"), managed_agent_id=agent.agent_id, status="active").first()
            if not gateway or not gateway.enabled or not binding or binding.key_id != value.get("key_id") or body.model not in {item["id"] for item in binding_models(db, gateway, binding)}:
                raise ApiError(403, "client.manual_credential_unavailable", "外部凭证或模型授权已变化", "The external credential or model authorization changed")
        response.headers["Cache-Control"] = "no-store"
        return value
    previous = _manual_handoff(db, client_id, token.id, local.local_agent_id, source)
    if previous and body.replace_request_id != previous["request_id"]:
        raise ApiError(409, "client.manual_already_issued", "已有手动领取记录，请重新读取后继续或明确重新领取", "A handoff already exists; reload to continue or explicitly replace it")
    plain = ""
    credential = None
    binding = None
    if source == "external_gateway":
        gateway = db.get(models.ExternalAIGateway, routing.get("external_gateway_id"))
        if not gateway or not gateway.enabled:
            raise ApiError(409, "client.external_gateway_unavailable", "外部网关未启用", "The external gateway is disabled")
        binding = db.query(models.ExternalGatewayAgentBinding).filter_by(gateway_id=gateway.id, managed_agent_id=agent.agent_id).first()
        if not binding or binding.status != "active":
            raise ApiError(409, "client.external_binding_unavailable", "请先读取外部网关模型目录", "Load the external model catalog first")
        if body.model not in {item["id"] for item in binding_models(db, gateway, binding)}:
            raise ApiError(403, "client.model_not_delegated", "当前 Agent 无权使用所选模型", "This Agent cannot use the selected model")
        plain = unprotect_secret(binding.api_key_encrypted)
        if not plain:
            raise ApiError(409, "external_gateway.credential_unavailable", "外部 Agent API Key 不可用", "The external Agent API key is unavailable")
    else:
        allowed = _load(token.allowed_models_json, [])
        model = db.query(models.ModelEndpoint).join(models.ModelProvider).filter(models.ModelEndpoint.name == body.model, models.ModelEndpoint.enabled.is_(True), models.ModelProvider.enabled.is_(True)).first()
        if not model or (allowed and body.model not in allowed):
            raise ApiError(403, "client.model_not_delegated", "当前客户端无权配置所选模型", "This Client cannot configure the selected model")
        policy = client_governance.policy_view(db, client_id)
        plain = _new_token()
        credential = models.AccessToken(
            name=f"{agent.name} · 手动模型配置"[:128], token_type="agent_runtime", token_hash=_hash_token(plain), token_prefix=plain[:12],
            bound_agent_id=agent.agent_id, issued_by_client_token_id=token.id, scopes_json=_dump(["model:chat"]),
            allowed_models_json=_dump([body.model]), allowed_ips_json=token.allowed_ips_json,
            expires_at=token.expires_at, user_id=token.user_id, group_id=token.group_id,
            privacy_policy_id=token.privacy_policy_id,
            max_body_kb=token.max_body_kb, max_concurrent_requests=token.max_concurrent_requests,
            prompt_guard_mode=policy["prompt_guard"]["mode"], prompt_guard_llm_review=policy["prompt_guard"]["llm_review"],
            enable_compression=policy["compression"]["enabled"], compression_level=policy["compression"]["level"], created_by=f"client:{client_id}")
        db.add(credential)
        db.flush()
    # Only an explicitly replaced manual handoff may be revoked; automatic configurations have a separate lifecycle.
    if previous and previous.get("credential_id"):
        old = db.get(models.AccessToken, previous["credential_id"])
        if old and old.issued_by_client_token_id == token.id and old.bound_agent_id == agent.agent_id:
            old.status, old.revoked_at, old.revoked_by = "revoked", datetime.utcnow(), f"client:{client_id}:manual-replacement"
    value = {**body.model_dump(exclude={"replace_request_id"}), "issuer_id": token.id, "bound_agent_id": agent.agent_id,
             "credential_id": credential.id if credential else None, "key_id": binding.key_id if binding else None,
             "expires_at": credential.expires_at.isoformat() + "Z" if credential and credential.expires_at else None,
             "gateway_url": gateway.model_base_url if source == "external_gateway" else settings.MODEL_GATEWAY_PUBLIC_URL}
    db.add(models.ClientTask(client_id=client_id, task_type="manual_model_credential", request_key=key,
                            status="succeeded", payload_json=_dump(value), finished_at=datetime.utcnow()))
    db.add(models.ClientEvent(client_id=client_id, agent_type=local.agent_type, event_type="manual_model_credential_issued", details_json=_dump({**value, "status": "succeeded"})))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {**value, "token": plain}


@router.post("/{client_id}/model-catalog/refresh")
def refresh_external_model_catalog(
    client_id: str,
    body: schemas.ClientExternalModelCatalogRequest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    routing = client_governance.policy_view(db, client_id)["model_routing"]
    if not routing.get("client_select_model", True):
        raise ApiError(
            403,
            "client.external_model_selection_disabled",
            "平台策略未允许客户端自主选择外部模型",
            "The platform policy does not allow Client-side external model selection",
        )
    client_agent, managed_agent = _catalog_target(db, client, body)
    if managed_agent is None:
        if not token.allow_agent_credential_issuance:
            raise ApiError(403, "client.agent_credential_issuance_disabled", "当前客户端凭证未开启创建运行身份的权限", "This Client credential cannot create runtime identities")
        managed_agent = _ensure_client_managed_agent(
            db, client=client, client_agent=client_agent, token=token, model_name=""
        )
        client_agent.managed_agent_id = managed_agent.agent_id
        db.flush()
    if not _token_can_use_agent(db, token, managed_agent):
        raise ApiError(404, "agent.not_found", "平台 Agent 不存在或无权使用", "Managed Agent not found")
    return _external_catalog_response(db, client=client, client_agent=client_agent, managed_agent=managed_agent)


@router.post("/{client_id}/external-model-catalog")
def admin_external_model_catalog(
    client_id: str,
    body: schemas.ClientExternalModelCatalogRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    client = _client_or_404(db, client_id)
    _ensure_visible(client, current_user)
    client_agent, managed_agent = _catalog_target(db, client, body)
    if managed_agent is None:
        managed_agent = _ensure_inventory_agent_identity(
            db,
            client=client,
            client_agent=client_agent,
            owner=current_user.username,
            source="external_model_catalog",
        )
        client_agent.managed_agent_id = managed_agent.agent_id
        client_agent.takeover_status = "managed"
        db.flush()
    return _external_catalog_response(db, client=client, client_agent=client_agent, managed_agent=managed_agent)


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
    _replace_recovery_inventory(db, client_id, body.recovery)
    ensure_client_inventory_identities(db, row, owner=token.created_by, group_id=token.group_id)
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
    observed_at = body.observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo:
        observed_at = observed_at.astimezone(timezone.utc).replace(tzinfo=None)
    values = dict(client_id=client_id, event_type=body.event_type, agent_type=body.agent_type,
                  skill_name=body.skill_name, details_json=_dump(body.details),
                  observation_count=body.observation_count, last_seen_at=observed_at)
    if body.delivery_id:
        row, replay = save_delivery(db, client_id, body, observed_at)
        if replay:
            db.commit()
            return {"ok": True, "event_id": row.id, "delivery_id": body.delivery_id, "durable": True}
    else:
        aggregate = body.event_type in {"skill_governance_recorded", "skill_governance_detected", "skill_governance_action"} and body.details.get("path") and body.details.get("signature")
        if aggregate:
            identity = [client_id, body.event_type, *[body.details.get(key) for key in
                        ("path", "signature", "trigger", "policy_version", "action", "status", "error_code", "task_id")]]
            key = hashlib.sha256(_dump(identity).encode()).hexdigest()
            statement = sqlite_insert(models.ClientEvent).values(**values, aggregate_key=key)
            statement = statement.on_conflict_do_update(index_elements=[models.ClientEvent.aggregate_key], set_={
                "observation_count": func.max(models.ClientEvent.observation_count, statement.excluded.observation_count),
                "last_seen_at": func.max(models.ClientEvent.last_seen_at, statement.excluded.last_seen_at),
                "details_json": case((statement.excluded.last_seen_at >= models.ClientEvent.last_seen_at, statement.excluded.details_json), else_=models.ClientEvent.details_json),
            })
            db.execute(statement)
            row = db.query(models.ClientEvent).filter_by(aggregate_key=key).one()
        else:
            row = models.ClientEvent(**values)
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
    return {"ok": True, "event_id": row.id, **({"delivery_id": body.delivery_id, "durable": True} if body.delivery_id else {})}


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
async def poll_tasks(
    client_id: str,
    request: Request,
    response: Response,
    wait_seconds: int = Query(0, ge=0, le=30),
    after_id: int = Query(0, ge=0),
    scan_ids: str = Query("", max_length=8192),
    scan_after_revision: int = Query(0, ge=0),
    include_events: bool = Query(False),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_manager),
):
    requested_scan_ids = {value.strip() for value in scan_ids.split(",") if value.strip()}

    def scan_events() -> list[dict]:
        if not include_events or not requested_scan_ids:
            return []
        # Never hold the request's authentication/session connection while a
        # long poll is suspended. Scan status materialization is a short,
        # independent transaction.
        scan_db = Session(bind=db.get_bind())
        try:
            return _scan_events(scan_db)
        finally:
            scan_db.close()

    def _scan_events(scan_db: Session) -> list[dict]:
        # The client supplies the versions it is actually waiting for. A
        # status transition is materialized as a ClientEvent, giving the
        # existing task long poll a durable, monotonic cursor without adding
        # another high-frequency request path.
        latest: dict[str, dict] = {}
        for row in scan_db.query(models.ClientEvent).filter(
            models.ClientEvent.client_id == client_id,
            models.ClientEvent.event_type == "platform_scan_status",
            func.json_extract(models.ClientEvent.details_json, "$.version_id").in_(requested_scan_ids),
        ).order_by(models.ClientEvent.id.desc()).all():
            details = _load(row.details_json, {})
            version_id = str(details.get("version_id") or "")
            if version_id and version_id in requested_scan_ids and version_id not in latest:
                latest[version_id] = {"revision": row.id, "details": details}
        for version_id in requested_scan_ids:
            entry = manager.get_skill(version_id, include_scan_report=False)
            if entry is None:
                continue
            status = entry.status.value
            runs = [run for run in manager.list_scan_runs(entry.skill_id) if run.status == "PENDING"]
            if runs:
                status = SkillStatus.PENDING.value
            previous = latest.get(version_id, {}).get("details", {}).get("status")
            if previous == status:
                continue
            row = models.ClientEvent(
                client_id=client_id,
                event_type="platform_scan_status",
                skill_name=entry.name,
                details_json=_dump({"version_id": version_id, "skill_id": entry.family_id or version_id, "status": status}),
            )
            scan_db.add(row)
            scan_db.flush()
            latest[version_id] = {"revision": row.id, "details": {"version_id": version_id, "skill_id": entry.family_id or version_id, "status": status}}
        scan_db.commit()
        rows = scan_db.query(models.ClientEvent).filter(
            models.ClientEvent.client_id == client_id,
            models.ClientEvent.event_type == "platform_scan_status",
            models.ClientEvent.id > scan_after_revision,
            func.json_extract(models.ClientEvent.details_json, "$.version_id").in_(requested_scan_ids),
        ).order_by(models.ClientEvent.id).limit(500).all()
        return [{"revision": row.id, **_load(row.details_json, {})} for row in rows if str(_load(row.details_json, {}).get("version_id") or "") in requested_scan_ids]

    def fetch():
        try:
            token = _runtime_token("client:read-tasks", authorization, request, db)
            _bind_client(token, client_id, db)
            _client_or_404(db, client_id)
            rows = db.query(models.ClientTask).filter_by(client_id=client_id, status="pending").filter(models.ClientTask.id > after_id).order_by(models.ClientTask.id).all()
            allowed = []
            for row in rows:
                try:
                    require_client_task(row.task_type)
                except LicenseError:
                    continue
                allowed.append({"id": row.id, "task_type": row.task_type, "payload": _load(row.payload_json, {})})
            return allowed
        finally:
            db.close()

    # Authenticate before allocating a waiting connection.
    rows = await run_in_threadpool(fetch)
    versions = await run_in_threadpool(_client_update_versions)
    for channel, version in versions.items():
        response.headers[f"X-Agent-Manager-Client-{channel.title()}-Version"] = version
    response.headers["Cache-Control"] = "private, no-store"
    events = await run_in_threadpool(scan_events)
    if rows or events or not wait_seconds:
        return {"tasks": rows, "scan_events": events} if include_events else rows
    hub = task_hub(db.get_bind())
    async with hub.subscribe(client_id) as wake:
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            wake.clear()
            # Subscribe first, then query again so a commit cannot fall in a gap.
            rows = await run_in_threadpool(fetch)
            events = await run_in_threadpool(scan_events)
            if rows or events:
                return {"tasks": rows, "scan_events": events} if include_events else rows
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0 or await request.is_disconnected():
                return []
            try:
                await asyncio.wait_for(wake.wait(), min(remaining, 1))
            except asyncio.TimeoutError:
                # Check disconnects without a database query for each waiter.
                while not wake.is_set() and asyncio.get_running_loop().time() < deadline:
                    if await request.is_disconnected():
                        return []
                    try:
                        await asyncio.wait_for(wake.wait(), min(1, deadline - asyncio.get_running_loop().time()))
                    except asyncio.TimeoutError:
                        pass
                if not wake.is_set():
                    rows = await run_in_threadpool(fetch)
                    events = await run_in_threadpool(scan_events)
                    return {"tasks": rows, "scan_events": events} if include_events else rows


@router.post("/{client_id}/skill-actions")
def request_skill_action(
    client_id: str,
    body: schemas.ClientSkillActionRequest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
    manager: AgentManager = Depends(get_manager),
):
    token = _runtime_token("client:request-skill-actions", authorization, request, db)
    _bind_client(token, client_id, db)
    client = _client_or_404(db, client_id)
    task = client_skill_actions.create_action(db, client, body, token.created_by or client_id, manager)
    db.commit()
    return {"id": task.id, "status": task.status, "task_type": task.task_type, "payload": _load(task.payload_json, {})}


@router.post("/{client_id}/model-configurations")
def request_model_configuration(
    client_id: str,
    body: schemas.ClientModelConfigurationRequest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    require_license("model_gateway")
    client_token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(client_token, client_id, db)
    client = _client_or_404(db, client_id)
    if not client_token.allow_agent_credential_issuance:
        raise ApiError(
            403,
            "client.agent_credential_issuance_disabled",
            "当前客户端凭证未开启为 Agent 自动创建运行凭证的权限",
            "This Client credential cannot automatically create Agent runtime credentials",
        )
    agent_type = body.agent_type.strip()
    local_agent_id = _local_agent_id(body.local_agent_id, agent_type)
    model_name = body.model.strip()
    if agent_type not in _MODEL_CONFIG_AGENT_TYPES:
        raise ApiError(
            400,
            "client.model_config_agent_unsupported",
            "当前 Agent 暂不支持自动配置模型",
            "This Agent does not support automatic model configuration",
        )
    _lock_model_task_agent(db, client_id, local_agent_id)
    client_agent = (
        db.query(models.ClientAgent)
        .filter(
            models.ClientAgent.client_id == client_id,
            models.ClientAgent.local_agent_id == local_agent_id,
            models.ClientAgent.agent_type == agent_type,
        )
        .first()
    )
    if not client_agent or not _load(client_agent.capabilities_json, {}).get("model_config_auto_apply"):
        raise ApiError(
            400,
            "client.model_config_agent_unsupported",
            "客户端未发现支持模型切换的目标 Agent",
            "The Client did not discover a target Agent that supports model switching",
        )
    requested_managed_agent_id = str(body.managed_agent_id or "").strip()
    if client_agent.managed_agent_id and requested_managed_agent_id not in {"", client_agent.managed_agent_id}:
        raise ApiError(
            409,
            "client.agent_identity_mismatch",
            "本机 Agent 身份与请求不一致，请刷新客户端清单",
            "The local Agent identity does not match the request; refresh the Client inventory",
        )
    if not client_agent.managed_agent_id:
        requested_agent = _ensure_client_managed_agent(
            db,
            client=client,
            client_agent=client_agent,
            token=client_token,
            model_name=model_name,
        )
        client_agent.managed_agent_id = requested_agent.agent_id
        client_agent.takeover_status = "managed"
        db.add(
            models.ClientEvent(
                client_id=client_id,
                event_type="local_agent_binding_updated",
                agent_type=agent_type,
                details_json=_dump(
                    {
                        "local_agent_id": local_agent_id,
                        "managed_agent_id": requested_agent.agent_id,
                        "source": "model_switch_auto_created",
                    }
                ),
            )
        )
    agent = (
        db.query(models.ManagedAgent)
        .filter(
            models.ManagedAgent.agent_id == client_agent.managed_agent_id,
            models.ManagedAgent.status == "active",
        )
        .first()
    )
    if not agent or not _token_can_use_agent(db, client_token, agent):
        raise ApiError(404, "agent.identity_not_found", "本机 Agent 身份不存在或未启用", "The local Agent identity is missing or disabled")
    source = body.source
    delegated_models = {
        str(item).strip()
        for item in _load(client_token.allowed_models_json, [])
        if str(item).strip()
    }
    if source == "internal" and delegated_models and model_name not in delegated_models:
        raise ApiError(
            403,
            "client.model_not_delegated",
            "当前客户端凭证不允许配置该模型",
            "The Client credential cannot configure this model",
        )
    model = None
    gateway = None
    external_binding = None
    if source == "internal":
        model = (
            db.query(models.ModelEndpoint)
            .join(models.ModelProvider, models.ModelProvider.id == models.ModelEndpoint.provider_id)
            .filter(
                models.ModelEndpoint.name == model_name,
                models.ModelEndpoint.enabled.is_(True),
                models.ModelProvider.enabled.is_(True),
            )
            .first()
        )
        if not model:
            raise ApiError(404, "model.not_found", "模型不存在或未启用", "The model is missing or disabled")
    else:
        routing = client_governance.policy_view(db, client_id)["model_routing"]
        if not routing.get("external_gateway_enabled"):
            raise ApiError(403, "client.external_gateway_disabled", "平台策略未允许使用外部 AI 网关", "The platform policy does not allow external AI gateways")
        if not routing.get("client_select_model", True):
            raise ApiError(
                403,
                "client.external_model_selection_disabled",
                "平台策略未允许客户端自主选择外部模型",
                "The platform policy does not allow Client-side external model selection",
            )
        if body.gateway_id not in (None, routing.get("external_gateway_id")):
            raise ApiError(403, "client.external_gateway_not_allowed", "所选外部网关不在平台策略范围内", "The selected external gateway is outside the platform policy")
        gateway = db.get(models.ExternalAIGateway, routing.get("external_gateway_id"))
        if not gateway or not gateway.enabled:
            raise ApiError(409, "client.external_gateway_unavailable", "外部 AI 网关不存在或未启用", "The external AI gateway is missing or disabled")
        external_binding = db.query(models.ExternalGatewayAgentBinding).filter_by(
            gateway_id=gateway.id, managed_agent_id=agent.agent_id
        ).first()
        if not external_binding:
            if not routing.get("auto_register_agent", True):
                raise ApiError(409, "client.external_agent_registration_required", "外部 Agent 尚未注册", "The external Agent has not been registered")
            external_binding = ensure_binding(db, gateway, agent, client_id=client_id)
        external_models = binding_models(db, gateway, external_binding)
        if model_name not in {item["id"] for item in external_models}:
            raise ApiError(404, "external_gateway.model_not_available", "当前外部 Agent 无权使用所选模型", "The selected model is unavailable to this external Agent")
    options = validate_model_options(agent_type, body.parameters, body.expected_revision, model)
    validate_parameter_version(agent_type, options["parameters"], client_agent.agent_version)
    validate_effective_parameters(agent_type, options["parameters"], reported_model_parameters(_load(client_agent.capabilities_json, {})), model)
    now = datetime.utcnow()
    for active_task in db.query(models.ClientTask).filter(
        models.ClientTask.client_id == client_id,
        models.ClientTask.task_type.in_(("apply_model_config", "verify_model_config", "restore_model_config")),
        models.ClientTask.status.in_(("pending", "running")),
    ).all():
        active_payload = _load(active_task.payload_json, {})
        if _local_agent_id(active_payload.get("local_agent_id"), str(active_payload.get("agent_type") or "")) == local_agent_id:
            started_at = active_task.started_at or active_task.created_at
            if active_task.status == "running" and started_at and now - started_at >= _MODEL_CONFIG_TASK_STALE_AFTER:
                active_task.status = "failed"
                active_task.error = "model_config.task_timeout"
                active_task.finished_at = now
                _update_model_config_state(db, client_id, active_payload, "failed", active_task.error)
                continue
            raise ApiError(
                409,
                "client.model_config_in_progress",
                "该 Agent 正在切换模型",
                "A model switch is already running for this Agent",
            )
    payload = {
        "local_agent_id": local_agent_id,
        "agent_type": agent_type,
        "managed_agent_id": agent.agent_id,
        "model": model_name,
        **options,
    }
    if source == "external_gateway":
        payload.update({
            "source": "external_gateway",
            "model": model_name,
            "gateway_id": gateway.id,
            "external_binding_id": external_binding.id,
            "model_base_url": gateway.model_base_url,
            "gateway_source": "external",
            "credential_source": "external_gateway",
            "credential_type": "external_gateway_api_key",
            "verification_mode": "client_call",
        })
    else:
        payload["auto_issue_credential"] = True
        if settings.MODEL_GATEWAY_PUBLIC_URL:
            payload["model_base_url"] = settings.MODEL_GATEWAY_PUBLIC_URL
    task = models.ClientTask(
        client_id=client_id,
        task_type="apply_model_config",
        payload_json=_dump(payload),
        status="running",
        started_at=now,
    )
    db.add(task)
    client_agent.desired_model = model_name
    client_agent.model_config_status = "applying"
    client_agent.model_config_error = None
    client_agent.model_config_updated_at = now
    agent.default_model = model_name
    agent.updated_at = now
    db.commit()
    db.refresh(task)
    return {"id": task.id, "task_type": task.task_type, "payload": payload, "status": task.status}


@router.post("/{client_id}/tasks/{task_id}/model-preflight")
def preflight_model_task(
    client_id: str, task_id: int, body: schemas.ClientModelPreflightRequest, request: Request,
    authorization: str | None = Header(None), db: Session = Depends(get_db),
):
    token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(token, client_id, db)
    task = db.query(models.ClientTask).filter_by(id=task_id, client_id=client_id).first()
    if not task or task.task_type != "apply_model_config" or task.status not in {"pending", "running"}:
        raise ApiError(409, "client.task_not_active", "模型配置任务未处于可执行状态", "The model configuration task is not active")
    payload = _load(task.payload_json, {})
    kind = payload.get("agent_type")
    binding = db.query(models.ClientAgent).filter_by(client_id=client_id, agent_type=kind, local_agent_id=payload.get("local_agent_id")).first()
    agent = db.query(models.ManagedAgent).filter_by(agent_id=binding.managed_agent_id, status="active").first() if binding else None
    if not agent or agent.agent_id != payload.get("managed_agent_id"):
        raise ApiError(404, "agent.identity_not_found", "本机 Agent 身份不存在或未启用", "The local Agent identity is missing or disabled")
    external = payload.get("credential_source") == "external_gateway"
    model = None if external else db.query(models.ModelEndpoint).join(models.ModelProvider).filter(
        models.ModelEndpoint.name == payload.get("model"), models.ModelEndpoint.enabled.is_(True), models.ModelProvider.enabled.is_(True),
    ).first()
    if not external and not model:
        raise ApiError(404, "model.not_found", "模型不存在或未启用", "The model is missing or disabled")
    delegated = _load(token.allowed_models_json, [])
    if not external and delegated and model.name not in delegated:
        raise ApiError(403, "client.model_not_delegated", "当前客户端凭证不允许配置该模型", "The Client credential cannot configure this model")
    if external:
        external_binding = db.get(models.ExternalGatewayAgentBinding, payload.get("external_binding_id"))
        if not external_binding or external_binding.status != "active" or external_binding.managed_agent_id != agent.agent_id:
            raise ApiError(409, "client.external_binding_unavailable", "外部 Agent 绑定不可用", "The external Agent binding is unavailable")
    elif payload.get("auto_issue_credential"):
        if not token.allow_agent_credential_issuance:
            raise ApiError(403, "client.agent_credential_issuance_disabled", "当前客户端凭证未开启创建运行凭证的权限", "This Client credential cannot create runtime credentials")
    elif model.name not in _agent_model_names(db, agent):
        raise ApiError(403, "client.agent_model_not_authorized", "Agent 运行凭证未授权访问该模型", "The Agent runtime credential cannot access this model")
    if payload.get("expected_revision") and payload["expected_revision"] != body.revision:
        raise ApiError(409, "client.model_config_conflict", "配置已变化，请刷新后重试", "Configuration changed; refresh and retry")
    explicit = validate_model_options(kind, payload.get("parameters", {}), model=model)["parameters"]
    validate_parameter_version(kind, explicit, binding.agent_version)
    validate_effective_parameters(kind, explicit, body.current_parameters, model)
    return {"ok": True}


@router.post(
    "/{client_id}/tasks/{task_id}/agent-credential",
    response_model=schemas.ClientAgentCredentialResponse,
)
def issue_task_agent_credential(
    client_id: str,
    task_id: int,
    request: Request,
    body: schemas.ClientAgentCredentialRequest | None = None,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    client_token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(client_token, client_id, db)
    _client_or_404(db, client_id)
    if not client_token.allow_agent_credential_issuance:
        raise ApiError(
            403,
            "client.agent_credential_issuance_disabled",
            "当前客户端凭证未开启为 Agent 自动创建运行凭证的权限",
            "This Client credential cannot automatically create Agent runtime credentials",
        )
    task = (
        db.query(models.ClientTask)
        .filter(models.ClientTask.id == task_id, models.ClientTask.client_id == client_id)
        .first()
    )
    if not task:
        raise ApiError(404, "client.task_not_found", "客户端任务不存在", "Client task not found")
    if task.task_type != "apply_model_config":
        raise ApiError(
            400,
            "client.task_credential_not_applicable",
            "当前任务不需要创建 Agent 运行凭证",
            "This task does not require an Agent runtime credential",
        )
    if task.status not in {"pending", "running"}:
        raise ApiError(
            409,
            "client.task_not_active",
            "只有待执行或执行中的任务可以领取 Agent 运行凭证",
            "Only pending or running tasks may issue an Agent runtime credential",
        )
    payload = _load(task.payload_json, {})
    external = payload.get("credential_source") == "external_gateway"
    if body and body.credential_source != ("external_gateway" if external else "agent_runtime"):
        raise ApiError(409, "client.credential_source_mismatch", "领取的凭据来源与任务不一致", "The requested credential source does not match the task")
    if not external and not payload.get("auto_issue_credential"):
        raise ApiError(
            403,
            "client.task_credential_issuance_not_authorized",
            "该任务未授权自动创建 Agent 运行凭证",
            "This task is not authorized to create an Agent runtime credential",
        )
    agent_type = str(payload.get("agent_type") or "").strip()
    local_agent_id = _local_agent_id(payload.get("local_agent_id"), agent_type)
    model_name = str(payload.get("model") or "").strip()
    client_agent = (
        db.query(models.ClientAgent)
        .filter(
            models.ClientAgent.client_id == client_id,
            models.ClientAgent.local_agent_id == local_agent_id,
            models.ClientAgent.agent_type == agent_type,
        )
        .first()
    )
    if not client_agent or not client_agent.managed_agent_id:
        raise ApiError(
            400,
            "client.agent_identity_missing",
            "本机 Agent 身份尚未自动登记",
            "The local Agent identity has not been registered automatically",
        )
    agent = db.query(models.ManagedAgent).filter(
        models.ManagedAgent.agent_id == client_agent.managed_agent_id,
        models.ManagedAgent.status == "active",
    ).first()
    if not agent:
        raise ApiError(404, "agent.identity_not_found", "本机 Agent 身份不存在或未启用", "The local Agent identity is missing or disabled")
    if external:
        binding = db.get(models.ExternalGatewayAgentBinding, payload.get("external_binding_id"))
        gateway = db.get(models.ExternalAIGateway, payload.get("gateway_id"))
        if (
            not binding
            or not gateway
            or not gateway.enabled
            or binding.gateway_id != gateway.id
            or binding.managed_agent_id != agent.agent_id
            or binding.status != "active"
        ):
            raise ApiError(409, "client.external_binding_unavailable", "外部 Agent 绑定不可用", "The external Agent binding is unavailable")
        plain = unprotect_secret(binding.api_key_encrypted)
        if not plain:
            raise ApiError(409, "external_gateway.credential_unavailable", "外部 Agent API Key 不可用", "External Agent API key is unavailable")
        return schemas.ClientAgentCredentialResponse(
            token=plain,
            token_prefix=plain[:8],
            bound_agent_id=agent.agent_id,
            credential_type="external_gateway_api_key",
            credential_source="external_gateway",
            gateway_base_url=gateway.model_base_url,
            allowed_models=[model_name],
            allowed_mcp_gateways=[],
        )
    model = db.query(models.ModelEndpoint).join(models.ModelProvider).filter(
        models.ModelEndpoint.name == model_name,
        models.ModelEndpoint.enabled.is_(True),
        models.ModelProvider.enabled.is_(True),
    ).first()
    if not model:
        raise ApiError(404, "model.not_found", "模型不存在或未启用", "The model is missing or disabled")
    delegated_models = {
        str(item).strip()
        for item in _load(client_token.allowed_models_json, [])
        if str(item).strip()
    }
    if delegated_models and model.name not in delegated_models:
        raise ApiError(
            403,
            "client.model_not_delegated",
            "当前客户端凭证不允许配置该模型",
            "The Client credential cannot configure this model",
        )
    allowed_mcp_gateways = _agent_gateway_names(db, agent)
    plain, credential = _issue_agent_runtime_credential(
        db,
        client_token=client_token,
        client_id=client_id,
        agent=agent,
        model_name=model.name,
        allowed_mcp_gateways=allowed_mcp_gateways,
        task=task,
        previous_credential_hash=body.previous_credential_hash if body else None,
    )
    return schemas.ClientAgentCredentialResponse(
        token=plain,
        token_prefix=credential.token_prefix,
        bound_agent_id=agent.agent_id,
        credential_type="agent_runtime",
        credential_source="agent_runtime",
        allowed_models=[model.name],
        allowed_mcp_gateways=allowed_mcp_gateways,
    )


@router.post("/{client_id}/model-verification-evidence")
def model_verification_evidence(
    client_id: str, body: schemas.ClientModelVerificationEvidence, request: Request,
    authorization: str | None = Header(None), db: Session = Depends(get_db),
):
    from backend.model_verification import probe_evidence
    token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(token, client_id, db)
    agent = db.query(models.ClientAgent).filter_by(client_id=client_id, local_agent_id=body.local_agent_id, agent_type=body.agent_type).first()
    if not agent or not agent.managed_agent_id:
        raise ApiError(404, "client.agent_identity_missing", "未找到本机 Agent 身份", "Local Agent identity not found")
    return {"requests": probe_evidence(db, client_id, agent.managed_agent_id, body.challenge)}


@router.get("/{client_id}/tasks/{task_id}/skill-observation")
def skill_observation_policy(client_id: str, task_id: int, request: Request,
                             authorization: str | None = Header(None), db: Session = Depends(get_db)):
    token = _runtime_token('client:read-tasks', authorization, request, db)
    _bind_client(token, client_id, db)
    task = db.query(models.ClientTask).filter_by(id=task_id, client_id=client_id).first()
    from .. import aidr_skill_review
    if not task:
        aidr_skill_review.fail('observation_task_invalid', '采集任务不存在', 'Observation task unavailable', 404)
    result = aidr_skill_review.observation_policy(db, task)
    db.commit()
    return result


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
    if row.task_type == 'aidr_skill_observe':
        from .. import aidr_skill_review
        db.query(models.ClientTask).filter_by(id=row.id).update({'status':models.ClientTask.status}, synchronize_session=False)
        db.refresh(row)
        if aidr_skill_review.expire_task(row):
            db.commit()
        if row.status in {'succeeded', 'failed', 'cancelled'}:
            return {'ok':True, 'ignored':True, 'status':row.status}
        if body.status == 'running':
            row.status, row.started_at = 'running', datetime.utcnow()
        else:
            if row.status != 'running':
                aidr_skill_review.fail('observation_task_invalid', '采集任务尚未开始', 'Observation task has not started')
            if body.status == 'succeeded':
                if body.skill_observation is None:
                    aidr_skill_review.fail('observation_mismatch', '缺少采集回执', 'Observation receipt is required')
                try:
                    aidr_skill_review.complete_observation(db, row, body.skill_observation)
                except ApiError as exc:
                    row.status, row.finished_at = 'failed', datetime.utcnow()
                    row.error = exc.code.replace('aidr.skill_', 'aidr_skill_')
                    db.commit()
                    return {'ok':True, 'status':row.status}
            row.status, row.finished_at = body.status, datetime.utcnow()
            row.error = body.error if body.error and re.fullmatch(r'aidr_skill_[a-z_]{1,80}', body.error) else ('aidr_skill_observation_failed' if body.status == 'failed' else None)
        db.commit()
        return {'ok':True, 'status':row.status}
    if row.task_type == "aidr_plugin_action":
        payload = _load(row.payload_json, {})
        if body.status == "running":
            if payload.get("action") in {"enable", "disable"} and runtime_governance.policy_manages_receiver(db, client_id):
                db.query(models.ClientTask).filter_by(id=task_id, status="pending").update({"status": "cancelled", "error": "aidr_desktop_task_superseded", "finished_at": datetime.utcnow()})
                db.commit()
                return {"ok": True, "ignored": True, "status": "cancelled"}
            if payload.get("action") == "reconcile" and payload.get("policy_version") != client_governance.policy_view(db, client_id)["runtime_governance_version"]:
                db.query(models.ClientTask).filter_by(id=task_id, status="pending").update({"status": "cancelled", "error": "aidr_desktop_task_superseded", "finished_at": datetime.utcnow()})
                db.commit()
                return {"ok": True, "ignored": True, "status": "cancelled"}
            expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            if expires <= datetime.utcnow():
                db.query(models.ClientTask).filter_by(id=task_id, status="pending").update({"status": "failed", "error": "aidr_desktop_task_expired", "finished_at": datetime.utcnow()})
                db.commit()
                return {"ok": True, "ignored": True, "status": "failed"}
            changed = db.query(models.ClientTask).filter_by(id=task_id, client_id=client_id, status="pending").update({"status": "running", "started_at": datetime.utcnow()}, synchronize_session=False)
        else:
            if row.status != "running":
                return {"ok": True, "ignored": True, "status": row.status}
            if body.status == "succeeded":
                if body.aidr_result is None or (payload["action"] != "inspect" and body.aidr_result.managed_task != str(task_id)):
                    raise ApiError(409, "aidr.runtime_receipt_required", "缺少匹配的本机执行回执", "A matching local execution receipt is required")
                if (payload["action"] == "enable" and body.aidr_result.enabled is not True) or (payload["action"] == "disable" and body.aidr_result.enabled is not False):
                    raise ApiError(409, "aidr.runtime_receipt_required", "本机配置回执与任务目标不一致", "The local configuration receipt does not match the target")
                if payload["action"] == "reconcile" and (body.aidr_result.policy_version != payload["policy_version"] or not body.aidr_result.policy_applied_at
                        or body.aidr_result.enabled != runtime_governance.hook_target(payload["target"]) or body.aidr_result.policy_code != "aidr_desktop_policy_applied"):
                    raise ApiError(409, "aidr.runtime_receipt_required", "缺少匹配的策略应用证据", "Matching policy application evidence is required")
                runtime_governance.record(db, client_id, body.aidr_result)
                payload["receipt"] = body.aidr_result.model_dump()
            error_code = body.error
            if error_code and not re.fullmatch(r"aidr_[a-z0-9_]{1,90}", error_code):
                error_code = "aidr_desktop_receiver_failed"
            changed = db.query(models.ClientTask).filter_by(id=task_id, client_id=client_id, status="running").update({"status": body.status, "error": error_code, "payload_json": _dump(payload), "finished_at": datetime.utcnow()}, synchronize_session=False)
        db.commit()
        db.refresh(row)
        return {"ok": True, "ignored": not bool(changed), "status": row.status}
    if row.task_type in {"apply_model_config", "verify_model_config", "restore_model_config"} and body.status == "running":
        changed = db.query(models.ClientTask).filter_by(id=task_id, client_id=client_id, status="pending").update(
            {"status": "running", "started_at": datetime.utcnow()}, synchronize_session=False)
        if changed:
            _update_model_config_state(db, client_id, _load(row.payload_json, {}), "applying")
        db.commit()
        db.refresh(row)
        return {"ok": True, "ignored": not bool(changed), "status": row.status}
    target_version = _load(row.payload_json, {}).get("target_version")
    if row.task_type == "sync_policy" and target_version and body.status == "succeeded" and row.status in ("pending", "running"):
        if body.applied_policy_version != target_version:
            db.query(models.ClientTask).filter(
                models.ClientTask.id == task_id,
                models.ClientTask.status.in_(("pending", "running")),
            ).update({"status": "failed", "error": "policy_ack_required", "finished_at": datetime.utcnow()}, synchronize_session=False)
            db.commit()
            raise ApiError(409, "client.policy_ack_required", "客户端未确认应用目标策略版本，请升级或重试", "The client must confirm the applied policy version; upgrade or retry")
    if row.task_type in {"sync_policy", "skill_action", "remove_skill", "install_skill", "repair_skill"}:
        updates = {"status": body.status, "error": body.error}
        if body.status == "running":
            updates["started_at"] = func.coalesce(models.ClientTask.started_at, datetime.utcnow())
        else:
            updates["finished_at"] = datetime.utcnow()
        changed = db.query(models.ClientTask).filter(
            models.ClientTask.id == task_id, models.ClientTask.client_id == client_id,
            models.ClientTask.status.in_(("pending", "running")),
        ).update(updates, synchronize_session=False)
        if changed and row.task_type == "sync_policy" and body.status == "succeeded" and body.applied_desktop_menu_visibility is not None:
            client_governance.record_desktop_menus(db, client_id, 1, body.applied_desktop_menu_visibility)
        db.commit()
        db.refresh(row)
        return {"ok": True, "ignored": not bool(changed), "status": row.status}
    if row.status in {"cancelled", "succeeded", "failed"}:
        return {"ok": True, "ignored": True}
    row.status = body.status
    row.error = body.error
    payload = _load(row.payload_json, {})
    if row.task_type in {"verify_model_config", "restore_model_config"}:
        state = "applying" if body.status == "running" else "restored" if body.restored_after_failure else "failed"
        if body.status == "succeeded":
            state = "restored"
            if row.task_type == "verify_model_config":
                if payload.get("verification_mode") != "client_call":
                    agent = db.query(models.ClientAgent).filter_by(client_id=client_id, local_agent_id=payload["local_agent_id"], agent_type=payload["agent_type"]).first()
                    evidence = db.query(models.LlmRequestAudit).filter(models.LlmRequestAudit.request_id.in_(body.verification_request_ids),
                        models.LlmRequestAudit.agent_id == (agent.managed_agent_id if agent else ""),
                        models.LlmRequestAudit.model == payload["model"], models.LlmRequestAudit.status == "success",
                        models.LlmRequestAudit.credential_type == "agent_runtime",
                        models.LlmRequestAudit.created_at >= row.created_at).first()
                    if not evidence:
                        row.status = "failed"
                        row.error = "model_config.gateway_evidence_missing"
                        row.finished_at = datetime.utcnow()
                        _update_model_config_state(db, client_id, payload, "failed", row.error)
                        db.commit()
                        raise ApiError(409, "client.model_evidence_required", "缺少成功调用的网关证据", "Successful gateway call evidence is required")
                state = "verified"
        _update_model_config_state(db, client_id, payload, state, body.error)
        if body.applied_model is not None:
            agent = db.query(models.ClientAgent).filter_by(client_id=client_id, local_agent_id=payload["local_agent_id"], agent_type=payload["agent_type"]).first()
            if agent: agent.applied_model = body.applied_model
    if row.task_type == "apply_model_config":
        _update_model_config_state(
            db,
            client_id,
            payload,
            {"running": "applying", "succeeded": "pending_restart", "failed": "failed", "cancelled": "cancelled"}[
                body.status
            ],
            body.error,
        )
    if body.status == "running":
        row.started_at = datetime.utcnow()
    else:
        row.finished_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


def _governance_scope(db, scope, user):
    if scope == client_governance.DEFAULT_SCOPE:
        if user.role != "super_admin":
            raise ApiError(403, "client.default_policy_forbidden", "只有超级管理员可配置平台默认策略", "Only super administrators can configure the default policy")
    else:
        _ensure_visible(_client_or_404(db, scope), user)


@router.get("/governance/default")
def get_default_governance(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    return {**client_governance.policy_view(db), "editable": current_user.role == "super_admin"}


@router.post("/governance/default/preview")
def preview_default_governance(body: client_governance.PolicyChange, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    _governance_scope(db, client_governance.DEFAULT_SCOPE, current_user)
    return client_governance.preview(db, client_governance.DEFAULT_SCOPE, body)


@router.put("/governance/default")
def save_default_governance(body: client_governance.PolicyChange, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    _governance_scope(db, client_governance.DEFAULT_SCOPE, current_user)
    previous_runtime = client_governance.policy_view(db)["runtime_governance"]
    result = client_governance.save_policy(db, client_governance.DEFAULT_SCOPE, body, current_user)
    if result["version"] == body.expected_version:
        db.commit()
        return result
    _operation(db, current_user, "更新客户端默认分类策略", "default", _dump(jsonable_encoder(result)))
    if previous_runtime != result["runtime_governance"]:
        _operation(db, current_user, "aidr.runtime_policy_changed", "default", _dump({"version": result["runtime_governance_version"], "before": previous_runtime, "after": result["runtime_governance"]}))
    db.commit()
    return result


@router.get("/{client_id}/governance")
def get_client_governance(client_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    _governance_scope(db, client_id, current_user)
    client = _client_or_404(db, client_id)
    return client_governance.policy_view(db, client_id)


@router.post("/{client_id}/governance/preview")
def preview_client_governance(client_id: str, body: client_governance.PolicyChange, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    _governance_scope(db, client_id, current_user)
    return client_governance.preview(db, client_id, body)


@router.put("/{client_id}/governance")
def save_client_governance(client_id: str, body: client_governance.PolicyChange, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user)):
    _governance_scope(db, client_id, current_user)
    previous_runtime = client_governance.policy_view(db, client_id)["runtime_governance"]
    result = client_governance.save_policy(db, client_id, body, current_user)
    if result["version"] == body.expected_version:
        db.commit()
        return result
    if previous_runtime != result["runtime_governance"]:
        _operation(db, current_user, "aidr.runtime_policy_changed", client_id, _dump({"version": result["runtime_governance_version"], "before": previous_runtime, "after": result["runtime_governance"]}))
    _operation(db, current_user, "更新客户端分类策略", client_id, _dump(jsonable_encoder(result)))
    db.commit()
    return result


@router.get("")
def list_clients(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    query = db.query(models.ManagedClient)
    if current_user.role != "super_admin":
        query = query.filter(models.ManagedClient.registered_by == current_user.username)
    rows = query.order_by(models.ManagedClient.id.desc()).all()
    related = _client_related(db, rows)
    return [_client_response(db, row, related=related[row.client_id]) for row in rows]


@router.put("/{client_id}/assignment")
def update_client_assignment(
    client_id: str,
    body: schemas.ClientAssignmentFields,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _client_or_404(db, client_id)
    _ensure_visible(row, current_user)
    before = {key: getattr(row, key) for key in body.model_fields_set}
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    _operation(db, current_user, "client.assignment_updated", client_id,
               _dump({"before": before, "after": body.model_dump(exclude_unset=True)}))
    db.commit()
    return _client_response(db, row)


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
    event_page: int = Query(1, ge=1),
    event_page_size: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _client_or_404(db, client_id)
    _ensure_visible(row, current_user)
    result = _client_response(db, row)
    result["tasks"] = _task_history(db, client_id)
    events = db.query(models.ClientEvent).filter(
        models.ClientEvent.client_id == client_id,
        models.ClientEvent.event_type.notin_(("client_registered", "takeover_completed")),
    )
    total = events.count()
    event_page = min(event_page, max(1, (total + event_page_size - 1) // event_page_size))
    rows = events.order_by(client_event_records.expressions()[2].desc(), models.ClientEvent.id.desc()).offset((event_page - 1) * event_page_size).limit(event_page_size).all()
    result["events"] = _event_history(db, client_id, rows=rows)
    result["events_total"] = total
    result["event_page"] = event_page
    result["event_page_size"] = event_page_size
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


@router.get("/{client_id}/agent-workspace")
def get_agent_workspace(
    client_id: str, local_agent_id: str = Query(..., min_length=1, max_length=512),
    before: int = Query(2**63-1, ge=1), limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_admin_user),
):
    client = _client_or_404(db, client_id)
    _ensure_visible(client, current_user)
    local = db.query(models.ClientAgent).filter(models.ClientAgent.client_id == client_id, or_(
        models.ClientAgent.local_agent_id == local_agent_id,
        and_(or_(models.ClientAgent.local_agent_id.is_(None), models.ClientAgent.local_agent_id == ''), models.ClientAgent.agent_type == local_agent_id),
    )).first()
    if local is None:
        raise ApiError(404, 'client.agent_not_found', '此安装入口已不在客户端清单中', 'This installation is no longer in the client inventory')
    classification = client_governance.policy_view(db, client_id)
    agent = {
        'local_agent_id': _local_agent_id(local.local_agent_id, local.agent_type), 'agent_type': local.agent_type,
        'managed_agent_id': local.managed_agent_id, 'version': local.agent_version,
        'install_path': local.install_path, 'skills_path': local.skills_path,
        'skill_management_supported': local.skill_management_supported,
        'asset_inventory': asset_inventory(_load(local.capabilities_json, {})),
        'capabilities': {**_load(local.capabilities_json, {}), **({'model_config_contract': contract_for_version(local.agent_type, local.agent_version)} if local.agent_type in MODEL_ADAPTERS else {})},
        'desired_model': local.desired_model, 'applied_model': local.applied_model,
        'model_config_status': local.model_config_status, 'model_config_error': local.model_config_error,
        'model_config_updated_at': local.model_config_updated_at,
    }
    agent['skills'] = [{
        'skill_id': skill.skill_id, 'version_id': skill.version_id, 'version_no': skill.version_no,
        'name': skill.skill_name, 'path': skill.skill_path, 'signature': skill.signature,
        'status': skill.status, 'governance': _load(skill.governance_json, None),
    } for skill in db.query(models.ClientSkillInstall).filter_by(client_id=client_id, agent_type=local.agent_type).all()
      if installation_owns_path(agent, skill.skill_path, client.os)]
    data = {
        'client_id': client_id, 'name': client.name, 'os': client.os, 'arch': client.arch,
        'status': 'online' if client.last_seen_at and datetime.utcnow() - client.last_seen_at <= _CLIENT_ONLINE_WINDOW else 'offline',
        'classification': classification, 'model_routing': classification['model_routing'], 'agents': [agent],
        'recovery': [value for record in db.query(models.ClientRecoveryRecord).filter_by(client_id=client_id).all()
                     if installation_owns_path(agent, (value := _load(record.details_json, {})).get('original_path'), client.os)],
    }
    task = models.ClientTask
    local_id = func.json_extract(task.payload_json, '$.local_agent_id')
    product = func.json_extract(task.payload_json, '$.agent')
    rows = db.query(task).filter(task.client_id == client_id, task.id < before, or_(
        local_id == local_agent_id,
        and_(task.task_type == 'aidr_plugin_action', product == agent['agent_type']),
    )).order_by(task.id.desc()).limit(limit + 1).all()
    data['tasks'] = _task_history(db, client_id, rows=rows[:limit])
    data['tasks_has_more'] = len(rows) > limit
    data['tasks_next_before'] = rows[limit - 1].id if len(rows) > limit else None
    return data


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
        if client_governance.policy_view(db, client_id)["enabled"]:
            raise ApiError(409, "client.classification_policy_active", "请通过分类策略配置处置方式", "Configure actions through the classification policy")
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
    if not scan_allowed():
        db.commit()
        return {"client_id": client_id, "mode": row.policy_mode, "governance_mode": row.governance_mode, "sync_task_id": None}
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


def _lock_model_task_agent(db, client_id, local_id):
    # Serialize creation against the Agent row in the same database transaction.
    # A no-op UPDATE also takes the write lock on SQLite, where FOR UPDATE does not.
    db.query(models.ClientAgent).filter_by(client_id=client_id, local_agent_id=local_id).update(
        {"id": models.ClientAgent.id}, synchronize_session=False)


def _create_model_operation(db, client_id, operation, payload, actor):
    kind = str(payload.get("agent_type") or "")
    local_id = _local_agent_id(payload.get("local_agent_id"), kind)
    _lock_model_task_agent(db, client_id, local_id)
    agent = db.query(models.ClientAgent).filter_by(client_id=client_id, agent_type=kind, local_agent_id=local_id).first()
    caps = _load(agent.capabilities_json, {}) if agent else {}
    state = caps.get("model_config_state") or {}
    if not agent or not state.get("change_id"):
        raise ApiError(409, "client.model_config_required", "请先同步已写入的模型配置", "Synchronize a written model configuration first")
    if operation == "verify_model_config" and not caps.get("model_config_verification"):
        raise ApiError(400, "client.model_verification_unavailable", "此 Agent 暂无自动调用验证方式", "Automatic call verification is unavailable for this Agent")
    if operation == "restore_model_config" and not state.get("can_restore"):
        raise ApiError(409, "client.model_restore_conflict", "当前配置已变化或没有可恢复备份", "Configuration changed or no recoverable backup exists")
    if payload.get("expected_revision") != state.get("revision") or payload.get("change_id") != state.get("change_id"):
        raise ApiError(409, "client.model_revision_conflict", "配置已变化，请刷新后重试", "Configuration changed; refresh and retry")
    normalized = {"agent_type": kind, "local_agent_id": local_id, "change_id": state["change_id"],
                  "expected_revision": state["revision"], "model": state.get("model", "")}
    for key in ("gateway_source", "credential_source", "verification_mode"):
        if state.get(key):
            normalized[key] = state[key]
    active = db.query(models.ClientTask).filter(models.ClientTask.client_id == client_id,
        models.ClientTask.task_type.in_(("apply_model_config", "verify_model_config", "restore_model_config")),
        models.ClientTask.status.in_(("pending", "running"))).all()
    for item in active:
        existing = _load(item.payload_json, {})
        if existing.get("local_agent_id") == local_id:
            if item.task_type == operation and existing == normalized:
                return item
            raise ApiError(409, "client.model_config_in_progress", "该 Agent 有正在执行的模型任务", "A model task is active for this Agent")
    task = models.ClientTask(client_id=client_id, task_type=operation, payload_json=_dump(normalized))
    db.add(task)
    db.flush()
    db.add(models.ClientEvent(client_id=client_id, agent_type=kind, event_type="model_operation_created",
        details_json=_dump({"task_id": task.id, "operation": operation, "actor": actor, "local_agent_id": local_id})))
    db.commit()
    db.refresh(task)
    return task


@router.post("/{client_id}/model-operations")
def request_model_operation(client_id: str, body: schemas.ClientTaskCreate, request: Request,
    authorization: str | None = Header(None), db: Session = Depends(get_db)):
    token = _runtime_token("client:read-tasks", authorization, request, db)
    _bind_client(token, client_id, db)
    _client_or_404(db, client_id)
    if body.task_type not in {"verify_model_config", "restore_model_config"}:
        raise ApiError(400, "client.model_operation_invalid", "模型操作无效", "Invalid model operation")
    task = _create_model_operation(db, client_id, body.task_type, body.payload, f"client:{client_id}")
    return {"id": task.id, "task_type": task.task_type, "payload": _load(task.payload_json, {}), "status": task.status}


@router.post("/{client_id}/tasks")
def create_task(
    client_id: str,
    body: schemas.ClientTaskCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
    manager: AgentManager = Depends(get_manager),
):
    require_client_task(body.task_type)
    client = _client_or_404(db, client_id)
    _ensure_visible(client, current_user)
    payload = dict(body.payload)
    if body.task_type == 'aidr_skill_observe':
        raise ApiError(422, 'aidr.skill_observation_task_invalid', '请从 Skill 行为记录请求重新采集', 'Request recollection from a Skill activity record')
    if body.task_type == "aidr_plugin_action":
        try:
            task = runtime_governance.create(db, client, payload)
        except ValidationError as exc:
            raise ApiError(422, "aidr.runtime_action_invalid", "运行治理任务参数无效", "Invalid runtime governance task parameters") from exc
        _operation(db, current_user, "aidr.runtime_task_created", client_id, f"task_id={task.id}")
        db.commit()
        return {"id": task.id, "status": task.status}
    if body.task_type in {"verify_model_config", "restore_model_config"}:
        task = _create_model_operation(db, client_id, body.task_type, payload, current_user.username)
        return {"id": task.id, "status": task.status}
    if body.task_type == "skill_action":
        try:
            action = schemas.ClientSkillActionRequest.model_validate(payload)
        except ValidationError as exc:
            raise ApiError(422, "client.action_payload_invalid", "处置任务参数不完整或无效", "The remediation task parameters are incomplete or invalid") from exc
        task = client_skill_actions.create_action(db, client, action, current_user.username, manager)
        _operation(db, current_user, "创建客户端处置任务", client_id, f"task_id={task.id}")
        db.commit()
        return {"id": task.id, "status": task.status}
    if body.task_type == "apply_model_config":
        agent_type = str(payload.get("agent_type") or "").strip()
        local_agent_id = _local_agent_id(payload.get("local_agent_id"), agent_type)
        model_name = str(payload.get("model") or "").strip()
        if not agent_type or not model_name:
            raise HTTPException(status_code=400, detail="模型配置任务缺少目标 Agent 或模型")
        _lock_model_task_agent(db, client_id, local_agent_id)
        client_agent = (
            db.query(models.ClientAgent)
            .filter(
                models.ClientAgent.client_id == client_id,
                models.ClientAgent.local_agent_id == local_agent_id,
                models.ClientAgent.agent_type == agent_type,
            )
            .first()
        )
        if not client_agent:
            raise ApiError(404, "client.agent_not_found", "客户端未发现目标 Agent", "Target Agent was not discovered")
        if not client_agent.managed_agent_id:
            issuance = _client_issuance_token(db, client_id)
            if not issuance:
                raise ApiError(403, "client.agent_credential_issuance_disabled", "客户端未授权创建独立运行身份", "The Client cannot create an independent runtime identity")
            bound = _ensure_client_managed_agent(db, client=client, client_agent=client_agent, token=issuance, model_name=model_name)
            client_agent.managed_agent_id = bound.agent_id

        capabilities = _load(client_agent.capabilities_json, {})
        if agent_type not in _MODEL_CONFIG_AGENT_TYPES or not capabilities.get("model_config_auto_apply"):
            raise HTTPException(status_code=400, detail="当前 Agent 暂不支持自动应用模型配置")
        active = db.query(models.ClientTask).filter(
            models.ClientTask.client_id == client_id,
            models.ClientTask.task_type.in_(("apply_model_config", "verify_model_config", "restore_model_config")),
            models.ClientTask.status.in_(("pending", "running")),
        ).all()
        if any(_local_agent_id(_load(task.payload_json, {}).get("local_agent_id"), agent_type) == local_agent_id for task in active):
            raise ApiError(409, "client.model_config_in_progress", "该 Agent 正在切换模型", "A model switch is already running for this Agent")
        source = str(payload.get("source") or "internal")
        if source not in {"internal", "external_gateway"}:
            raise ApiError(422, "client.model_source_invalid", "模型来源无效", "Invalid model source")
        target_model = None
        if source == "internal":
            target_model = db.query(models.ModelEndpoint).join(models.ModelProvider).filter(
                models.ModelEndpoint.name == model_name, models.ModelEndpoint.enabled.is_(True), models.ModelProvider.enabled.is_(True),
            ).first()
            if not target_model:
                raise ApiError(404, "model.not_found", "模型不存在或未启用", "The model is missing or disabled")
        options = validate_model_options(agent_type, payload.get("parameters", {}), payload.get("expected_revision"), target_model)
        validate_parameter_version(agent_type, options["parameters"], client_agent.agent_version)
        validate_effective_parameters(agent_type, options["parameters"], reported_model_parameters(capabilities), target_model)
        agent = db.query(models.ManagedAgent).filter(
            models.ManagedAgent.agent_id == client_agent.managed_agent_id,
        ).first()
        if not agent or agent.status != "active":
            raise HTTPException(status_code=404, detail="绑定的智能体不存在或未启用")
        issuance_token = _client_issuance_token(db, client_id)
        delegated_models = (
            {
                str(item).strip()
                for item in _load(issuance_token.allowed_models_json, [])
                if str(item).strip()
            }
            if issuance_token
            else set()
        )
        if source == "internal" and issuance_token and delegated_models and model_name not in delegated_models:
            raise ApiError(
                403,
                "client.model_not_delegated",
                "当前客户端凭证不允许配置该模型",
                "The Client credential cannot configure this model",
            )
        allowed_models = _agent_model_names(db, agent)
        if source == "internal" and model_name not in allowed_models:
            model = db.query(models.ModelEndpoint).filter(
                models.ModelEndpoint.name == model_name,
                models.ModelEndpoint.enabled.is_(True),
            ).first()
            if not model:
                raise ApiError(404, "model.not_found", "模型不存在或未启用", "The model is missing or disabled")
            if not issuance_token:
                raise ApiError(
                    403,
                    "client.agent_model_not_authorized",
                    "Agent 运行凭证未授权访问该模型，客户端凭证也未开启自动创建权限",
                    "The Agent runtime credential does not allow this model and the Client credential cannot create one",
                )
        task_payload = {
            "local_agent_id": local_agent_id,
            "agent_type": agent_type,
            "managed_agent_id": agent.agent_id,
            "model": model_name,
            **options,
        }
        if source == "external_gateway":
            routing = client_governance.policy_view(db, client_id)["model_routing"]
            if not routing.get("external_gateway_enabled"):
                raise ApiError(403, "client.external_gateway_disabled", "平台策略未允许使用外部 AI 网关", "The platform policy does not allow external AI gateways")
            gateway_id = routing.get("external_gateway_id")
            requested_gateway_id = payload.get("gateway_id")
            if requested_gateway_id not in (None, gateway_id):
                raise ApiError(403, "client.external_gateway_not_allowed", "所选外部网关不在平台策略范围内", "The selected external gateway is outside the platform policy")
            gateway = db.get(models.ExternalAIGateway, gateway_id)
            if not gateway or not gateway.enabled:
                raise ApiError(409, "client.external_gateway_unavailable", "外部 AI 网关不存在或未启用", "The external AI gateway is missing or disabled")
            binding = db.query(models.ExternalGatewayAgentBinding).filter_by(
                gateway_id=gateway.id, managed_agent_id=agent.agent_id
            ).first()
            if not binding:
                if not routing.get("auto_register_agent", True):
                    raise ApiError(409, "client.external_agent_registration_required", "外部 Agent 尚未注册", "The external Agent has not been registered")
                binding = ensure_binding(db, gateway, agent, client_id=client_id)
            external_models = binding_models(db, gateway, binding)
            if model_name not in {item["id"] for item in external_models}:
                raise ApiError(404, "external_gateway.model_not_available", "当前外部 Agent 无权使用所选模型", "The selected model is unavailable to this external Agent")
            task_payload.update({
                "source": "external_gateway",
                "gateway_id": gateway.id,
                "external_binding_id": binding.id,
                "model_base_url": gateway.model_base_url,
                "gateway_source": "external",
                "credential_source": "external_gateway",
                "credential_type": "external_gateway_api_key",
                "verification_mode": "client_call",
            })
        else:
            if settings.MODEL_GATEWAY_PUBLIC_URL:
                task_payload["model_base_url"] = settings.MODEL_GATEWAY_PUBLIC_URL
            if issuance_token:
                task_payload["auto_issue_credential"] = True
        payload = task_payload
        client_agent.desired_model = model_name
        client_agent.model_config_status = "pending"
        client_agent.model_config_error = None
        client_agent.model_config_updated_at = datetime.utcnow()
        agent.default_model = model_name
        agent.updated_at = datetime.utcnow()
    elif body.task_type in {"install_skill", "repair_skill"}:
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
        payload["expected_root"] = client_agent.skills_path
        payload["expected_targets"] = {
            item.skill_path: item.signature
            for item in db.query(models.ClientSkillInstall).filter_by(
                client_id=client_id, agent_type=agent_type,
            ).all() if item.skill_path
        }
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
        if not install.skill_path or not install.signature:
            raise ApiError(409, "client.skill_content_unavailable", "请先同步目标 Skill 的目录和内容指纹", "Synchronize the target Skill path and content fingerprint first")
        payload["skill_name"] = install.skill_name
        payload["path"] = install.skill_path
        payload["expected_signature"] = install.signature
        payload["actor"] = current_user.username
        payload["policy_version"] = client_governance.policy_view(db, client_id)["version"]
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
    if row.task_type in {"aidr_plugin_action", "skill_action", "remove_skill", "install_skill", "repair_skill", "apply_model_config", "verify_model_config", "restore_model_config"}:
        changed = db.query(models.ClientTask).filter(
            models.ClientTask.id == task_id, models.ClientTask.client_id == client_id,
            models.ClientTask.status == "pending",
        ).update({"status": "cancelled", "finished_at": datetime.utcnow()}, synchronize_session=False)
        if not changed:
            raise ApiError(409, "client.action_already_started", "处置任务已开始，无法中途取消，请等待结果", "Remediation has started and cannot be cancelled midway; wait for the result")
        if row.task_type in {"apply_model_config", "verify_model_config", "restore_model_config"}:
            _update_model_config_state(db, client_id, _load(row.payload_json, {}), "cancelled")
        _operation(db, current_user, "取消客户端任务", client_id, f"task_id={task_id}")
        db.commit()
        return {"id": task_id, "status": "cancelled"}
    row.status = "cancelled"
    row.finished_at = datetime.utcnow()
    if row.task_type == "apply_model_config":
        _update_model_config_state(db, client_id, _load(row.payload_json, {}), "cancelled")
    _operation(db, current_user, "取消客户端任务", client_id, f"task_id={task_id}")
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/{client_id}/tasks/{task_id}/retry")
def retry_task(
    client_id: str,
    task_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
    manager: AgentManager = Depends(get_manager),
):
    client = _client_or_404(db, client_id)
    _ensure_visible(client, current_user)
    row = db.query(models.ClientTask).filter(models.ClientTask.id == task_id, models.ClientTask.client_id == client_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="只有失败或已取消的任务可以重试")
    require_client_task(row.task_type)
    payload = _load(row.payload_json, {})
    if row.task_type == 'aidr_skill_observe':
        from .. import aidr_skill_review
        iam.check(db, current_user, 'clients:update')
        usage = aidr_skill_review.usage(db, client_id, payload['usage_id'])
        retry = aidr_skill_review.create_observation(db, usage, f'retry-task:{task_id}', current_user.username)
        _operation(db, current_user, 'aidr.skill_observation_requested', client_id, f"usage_id={usage.id}, task_id={retry['id']}")
        db.commit()
        return retry
    if row.task_type == "aidr_plugin_action":
        return _retry_runtime_task(db, client, row, current_user)
    if row.task_type in {"apply_model_config", "verify_model_config", "restore_model_config"}:
        local_id = _local_agent_id(payload.get("local_agent_id"), str(payload.get("agent_type") or ""))
        _lock_model_task_agent(db, client_id, local_id)
        active = db.query(models.ClientTask).filter(models.ClientTask.client_id == client_id,
            models.ClientTask.task_type.in_(("apply_model_config", "verify_model_config", "restore_model_config")),
            models.ClientTask.status.in_(("pending", "running"))).all()
        for task in active:
            if _load(task.payload_json, {}).get("local_agent_id") == local_id:
                if task.request_key == f"retry-task:{client_id}:{task_id}":
                    return {"id": task.id, "status": task.status}
                raise ApiError(409, "client.model_config_in_progress", "该 Agent 有正在执行的模型任务", "A model task is active for this Agent")
    if row.task_type == "sync_policy" and payload.get("target_version") and payload["target_version"] != client_governance.policy_view(db, client_id)["version"]:
        raise ApiError(409, "client.policy_superseded", "此任务已被较新策略版本取代，请查看最新同步任务", "A newer policy superseded this task; use the latest synchronization task")
    if row.task_type in {"skill_action", "remove_skill"}:
        if row.task_type == "remove_skill":
            if not payload.get("path") or not payload.get("expected_signature"):
                raise ApiError(409, "client.skill_content_unavailable", "此历史任务未绑定内容，请同步后从 Skill 列表重新创建操作", "This historical task has no content binding; synchronize and create a new action from the Skill list")
            request = {"action": "uninstall", "agent_type": payload["agent_type"], "path": payload["path"], "expected_signature": payload["expected_signature"]}
        else:
            request = payload["request"]
        action = schemas.ClientSkillActionRequest.model_validate({**request, "request_id": f"retry-task:{task_id}"})
        retry = client_skill_actions.create_action(db, client, action, current_user.username, manager)
        _operation(db, current_user, "重试客户端处置任务", client_id, f"task_id={task_id}, retry_task_id={retry.id}")
        db.commit()
        return {"id": retry.id, "status": retry.status}
    # The daemon retains terminal receipts by task ID. A retry is new work;
    # preserve the original payload, including its content preconditions.
    retry_key = f"retry-task:{client_id}:{task_id}"
    inserted = db.execute(sqlite_insert(models.ClientTask).values(
        client_id=client_id, task_type=row.task_type, payload_json=row.payload_json,
        request_key=retry_key,
    ).on_conflict_do_nothing(index_elements=[models.ClientTask.request_key]))
    retry = db.query(models.ClientTask).filter_by(request_key=retry_key).one()
    if inserted.rowcount and row.task_type == "apply_model_config":
        _update_model_config_state(db, client_id, _load(retry.payload_json, {}), "pending")
    _operation(db, current_user, "重试客户端任务", client_id, f"task_id={task_id}, retry_task_id={retry.id}")
    db.commit()
    return {"id": retry.id, "status": retry.status}


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
            family_id = (getattr(entry, "family_id", None) or entry.skill_id) if entry else None
            expected_signature = _cached_skill_signature(entry.skill_path, signature_cache) if entry and entry.skill_path else None
            authorized = bool(
                not strict
                or (
                    managed_agent
                    and allowed_refs is not None
                    and (entry and (entry.name in allowed_refs or entry.skill_id in allowed_refs or family_id in allowed_refs))
                )
            )
            content_matches = bool(expected_signature and local_skill.signature == expected_signature)
            risk = getattr(getattr(entry, "risk_level", None), "value", getattr(entry, "risk_level", None))
            approved = bool(entry and entry.status in (SkillStatus.APPROVED, SkillStatus.DEPLOYED))
            # APPROVED is the effective human/policy decision. Keep the scan
            # risk in the platform report, but do not let it override the
            # approval returned to managed clients.
            malicious = bool(content_matches and risk == "malicious" and not approved)
            certified = bool(approved and content_matches)
            allowed = bool(local_agent and authorized and certified)
            if not local_agent:
                reason = "local_agent_not_found"
            elif strict and not managed_agent:
                reason = "managed_agent_not_found"
            elif not entry:
                reason = "skill_not_found"
            elif strict and allowed_refs is not None and entry.name not in allowed_refs and entry.skill_id not in allowed_refs and family_id not in allowed_refs:
                reason = "agent_not_authorized"
            elif malicious:
                reason = "malicious"
            elif entry.status not in (SkillStatus.APPROVED, SkillStatus.DEPLOYED):
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
                    "skill_id": family_id,
                    "version_id": entry.skill_id if entry else None,
                    "status": entry.status.value if entry else None,
                    "expected_signature": expected_signature,
                    "certified": certified,
                    "malicious": malicious,
                    "rejected": client_governance.content_rejected(entry, content_matches),
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
    skill_id: str | None = Query(None),
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

    if skill_id:
        entry = _authorized_client_skill(
            db,
            manager,
            client,
            token,
            skill_id,
            None,
            agent_type,
            managed_agent_id,
        )
        return {"items": [_available_skill_item(entry)]}

    if client.governance_mode == "strict":
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == managed_agent_id).first()
        if not agent or binding.managed_agent_id != managed_agent_id or not _token_can_use_agent(db, token, agent):
            raise HTTPException(status_code=403, detail="客户端未绑定该智能体")
        entries = []
        seen = set()
        for ref in _load(agent.skill_names_json, []):
            entry = _manager_trusted_skill(manager, str(ref))
            if entry and entry.skill_id not in seen and entry.status == SkillStatus.APPROVED and entry.skill_path:
                entries.append(_available_skill_item(entry))
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


@router.get("/{client_id}/runtime-governance")
def runtime_governance_view(client_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user)):
    _ensure_visible(_client_or_404(db, client_id), user)
    return runtime_governance.view(db, client_id)


def _retry_runtime_task(db, client, row, user):
    payload = _load(row.payload_json, {})
    if payload.get("action") == "reconcile":
        task = runtime_governance.retry_reconcile(db, client, row)
        _operation(db, user, "aidr.runtime_task_retried", client.client_id, f"task_id={task.id}")
        db.commit()
        return {"id": task.id, "status": task.status}
    payload.pop("expires_at", None)
    payload.pop("receipt", None)
    payload["request_id"] = f"retry-{row.id}"
    latest = db.query(models.ClientTask).filter_by(client_id=client.client_id, task_type="aidr_plugin_action").order_by(models.ClientTask.id.desc()).first()
    if latest and latest.id > row.id and _load(latest.payload_json, {}).get("request_id") != payload["request_id"]:
        raise ApiError(409, "aidr.runtime_task_superseded", "已有较新的任务，请按当前目标创建操作", "Create an operation for the current target; a newer task already exists")
    task = runtime_governance.create(db, client, payload)
    _operation(db, user, "aidr.runtime_task_retried", client.client_id, f"task_id={task.id}")
    db.commit()
    return {"id": task.id, "status": task.status}
