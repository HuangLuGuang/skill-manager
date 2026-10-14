"""Scanner-facing API with dedicated scanner token authentication."""

from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent_manager.api.import_work import import_endpoint
from agent_manager.api.router import (
    RuntimeCheckResponse,
    PromptVerifyPayload,
    SubmitResponse,
    ToolCheckResponse,
    VerifySkillSignatureRequest,
    VerifySkillSignatureResponse,
    _extract_zip_with_nested_archives,
    _process_pending_submission_task,
    _resolve_skill_root,
    _scan_executor,
    _submit_directory_for_processing,
    get_manager,
)
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import AuditEvent, RegistryEntry, SkillOrigin, SkillStatus, SourceInfo
from agent_manager.core.scan_cache import compute_content_fingerprint
from agent_manager.core.scanner_tokens import DEFAULT_SCOPES, ScannerToken, ScannerTokenStore
from agent_manager.core.vetting import _load_manifest
from backend.models import AccessToken
from backend.api_errors import ApiError
from backend.routers.access_tokens import (
    ensure_agent_prompt_allowed,
    ensure_agent_skill_allowed,
    ensure_token_agent_allowed,
    resolve_access_token,
    resolve_agent_id,
)
from backend.sqlite_db import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v1", tags=["skill-scanner"])
admin_router = APIRouter(prefix="/api/v1", tags=["skill-scanner-admin"])
runtime_router = APIRouter(prefix="/api/v1/access", tags=["access-runtime"])


class ScannerTokenCreateRequest(BaseModel):
    name: str
    scopes: list[str] = DEFAULT_SCOPES
    expires_at: datetime | None = None
    allowed_ips: list[str] = []
    max_upload_mb: int = 50
    max_concurrent_jobs: int = 2
    created_by: str | None = None


class ScannerTokenCreateResponse(BaseModel):
    token: str
    record: dict[str, Any]


class ScannerTokenListResponse(BaseModel):
    items: list[dict[str, Any]]


class ScannerDownloadInfo(BaseModel):
    items: list[dict[str, Any]]


class ScannerSubmitResponse(SubmitResponse):
    detail_url: str | None = None


@dataclass
class ScannerAuthContext:
    name: str
    max_upload_mb: int
    author: str | None = None
    token_name: str | None = None
    legacy_token: ScannerToken | None = None
    access_token: AccessToken | None = None


def _submission_principal(scanner_auth: ScannerAuthContext) -> str:
    token = scanner_auth.access_token
    if token and token.token_type == "client" and token.bound_client_id:
        return f"client:{token.bound_client_id}"
    if token:
        return f"access-token:{token.id}"
    if scanner_auth.legacy_token:
        return f"scanner-token:{scanner_auth.legacy_token.id}"
    return ""


def _source_owned_by(scanner_auth: ScannerAuthContext, entry: RegistryEntry) -> bool:
    allowed_owners = {scanner_auth.name, scanner_auth.author or "", scanner_auth.token_name or ""}
    return entry.source.author in allowed_owners or entry.source.token_name in allowed_owners


def _submission_owned_by(scanner_auth: ScannerAuthContext, entry: RegistryEntry) -> bool:
    principal = _submission_principal(scanner_auth)
    return _source_owned_by(scanner_auth, entry) or bool(principal and principal in entry.submission_principals)


def _grant_submission_access(mgr: AgentManager, scanner_auth: ScannerAuthContext, entry: RegistryEntry) -> None:
    principal = _submission_principal(scanner_auth)
    if not principal:
        return
    entry.submission_principals = mgr.registry.grant_submission_principal(entry.skill_id, principal)


def _fingerprint_skill_dir(skill_dir: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total_bytes = 0
    # Match the Go scanner's lexical ordering of relative POSIX path strings.
    for path in sorted(
        (item for item in skill_dir.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(skill_dir).as_posix(),
    ):
        if path.is_symlink():
            continue
        rel = path.relative_to(skill_dir).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        size = path.stat().st_size
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


def _scanner_release_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scanner" / "releases"


def _skill_verifier_dir() -> Path:
    base_dir = Path(__file__).resolve().parents[2] / "demo"
    return base_dir / "agent-manager-skill-verifier" / "skills" / "agent-manager-skill-verifier"


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for.strip():
        return forwarded_for.split(",", 1)[0].strip()
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else None


def _access_token_audit_metadata(
    request: Request,
    token: AccessToken,
    agent_id: str | None,
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "client_ip": _client_ip(request),
        "token_id": token.id,
        "token_name": token.name,
        "token_type": token.token_type,
        "token_prefix": token.token_prefix,
        "bound_agent_id": token.bound_agent_id,
        "user_id": token.user_id,
        "group_id": token.group_id,
    }


def _log_runtime_blocked_event(
    mgr: AgentManager,
    *,
    event_type: str,
    skill_name: str,
    request: Request,
    token: AccessToken,
    agent_id: str | None,
    reason: str,
    entry: RegistryEntry | None = None,
    extra_details: dict[str, Any] | None = None,
) -> None:
    details = _access_token_audit_metadata(request, token, agent_id)
    details["reason"] = reason
    if extra_details:
        details.update(extra_details)
    mgr.registry.log_event(
        AuditEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            skill_id=entry.skill_id if entry else "unknown",
            skill_name=entry.name if entry else skill_name,
            actor=agent_id,
            details=details,
        )
    )


def _ensure_agent_skill_allowed_or_audit(
    mgr: AgentManager,
    agent,
    skill_name: str,
    *,
    request: Request,
    token: AccessToken,
    agent_id: str | None,
    entry: RegistryEntry | None = None,
    event_type: str = "skill_load_blocked",
    extra_details: dict[str, Any] | None = None,
) -> None:
    try:
        ensure_agent_skill_allowed(
            agent,
            skill_name,
            entry.skill_id if entry else None,
            entry.family_id if entry else None,
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            _log_runtime_blocked_event(
                mgr,
                event_type=event_type,
                skill_name=skill_name,
                request=request,
                token=token,
                agent_id=agent_id,
                reason=str(exc.detail),
                entry=entry,
                extra_details=extra_details,
            )
        raise


def _scanner_release_files() -> list[dict[str, Any]]:
    release_dir = _scanner_release_dir()
    if not release_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(release_dir.iterdir()):
        if not path.is_file():
            continue
        if not (path.name.startswith("skill-scanner-cli-") or path.name.startswith("skill-scanner-gui-")):
            continue
        stat = path.stat()
        items.append({
            "name": path.name,
            "platform": path.name.removeprefix("skill-scanner-"),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return items


def get_token_store(mgr: AgentManager = Depends(get_manager)) -> ScannerTokenStore:
    return ScannerTokenStore(mgr.registry.data_dir)


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing access token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="invalid authorization header")
    return token.strip()


def _validate_scanner_token(
    required_scope: str,
    request: Request,
    authorization: str | None,
    store: ScannerTokenStore,
) -> ScannerToken:
    plain = _extract_bearer(authorization)
    try:
        return store.validate(plain, required_scope, client_ip=request.client.host if request.client else None)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def require_scanner_submit_token(
    request: Request,
    authorization: str | None = Header(None),
    store: ScannerTokenStore = Depends(get_token_store),
    db: Session = Depends(get_db),
) -> ScannerAuthContext:
    return _validate_scanner_auth(("scanner:submit", "client:submit-skill"), request, authorization, store, db)


def require_scanner_read_token(
    request: Request,
    authorization: str | None = Header(None),
    store: ScannerTokenStore = Depends(get_token_store),
    db: Session = Depends(get_db),
) -> ScannerAuthContext:
    return _validate_scanner_auth(("scanner:read-own-results", "client:submit-skill"), request, authorization, store, db)


def _validate_scanner_auth(
    required_scope: str | tuple[str, ...],
    request: Request,
    authorization: str | None,
    store: ScannerTokenStore,
    db: Session,
) -> ScannerAuthContext:
    plain = _extract_bearer(authorization)
    if plain.startswith("amat_"):
        token = resolve_access_token(db, authorization, required_scope=required_scope, request=request)
        if isinstance(required_scope, tuple) and token.token_type not in {"scanner", "client"}:
            raise HTTPException(status_code=403, detail="当前凭证不能提交 Skill")
        author = _access_token_author(db, token)
        return ScannerAuthContext(
            name=token.name,
            max_upload_mb=token.max_upload_mb,
            author=author,
            token_name=token.name,
            access_token=token,
        )
    legacy_scope = required_scope[0] if isinstance(required_scope, tuple) else required_scope
    legacy = _validate_scanner_token(legacy_scope, request, authorization, store)
    return ScannerAuthContext(
        name=legacy.name,
        max_upload_mb=legacy.max_upload_mb,
        author=legacy.created_by or legacy.name,
        token_name=legacy.name,
        legacy_token=legacy,
    )


def _access_token_author(db: Session, token: AccessToken) -> str:
    if token.user_id:
        from backend import models

        user = db.query(models.User).filter(models.User.id == token.user_id).first()
        if user:
            return user.username
    return token.created_by or token.name


def require_runtime_verify_token(
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> AccessToken:
    return resolve_access_token(db, authorization, required_scope="runtime:verify-signature", request=request)


def require_runtime_can_load_token(
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> AccessToken:
    return resolve_access_token(db, authorization, required_scope="runtime:can-load", request=request)


def require_runtime_check_tool_token(
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> AccessToken:
    return resolve_access_token(db, authorization, required_scope="runtime:check-tool", request=request)


@admin_router.get("/scanner/tokens", response_model=ScannerTokenListResponse)
def list_scanner_tokens(store: ScannerTokenStore = Depends(get_token_store)):
    return ScannerTokenListResponse(items=[token.public_dict() for token in store.list()])


@admin_router.post("/scanner/tokens", response_model=ScannerTokenCreateResponse)
def create_scanner_token(body: ScannerTokenCreateRequest, store: ScannerTokenStore = Depends(get_token_store)):
    raise ApiError(
        410,
        "credential.legacy_scanner_token_issuance_removed",
        "旧 Scanner Token 已停止签发，请在统一凭证中心创建 Scanner 接入凭证",
        "Legacy Scanner Token issuance has been removed; create a Scanner credential in the Credential Center",
    )


@admin_router.post("/scanner/tokens/{token_id}/revoke")
def revoke_scanner_token(token_id: str, store: ScannerTokenStore = Depends(get_token_store)):
    try:
        token = store.revoke(token_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Scanner token not found") from exc
    return token.public_dict()


@runtime_router.get("/runtime/can-load/{skill_name}", response_model=RuntimeCheckResponse)
def token_runtime_can_load(
    skill_name: str,
    request: Request,
    skill_path: str | None = None,
    agent_id: str | None = None,
    x_agent_id: str | None = Header(None, alias="X-Agent-ID"),
    token: AccessToken = Depends(require_runtime_can_load_token),
    db: Session = Depends(get_db),
    mgr: AgentManager = Depends(get_manager),
):
    if skill_path:
        raise HTTPException(
            status_code=400,
            detail="access runtime can-load does not accept skill_path; use verify-skill-signature first",
        )
    resolved_agent_id = resolve_agent_id(agent_id, x_agent_id)
    agent = ensure_token_agent_allowed(db, token, resolved_agent_id)
    entry = mgr.get_skill(skill_name, include_scan_report=False)
    _ensure_agent_skill_allowed_or_audit(
        mgr,
        agent,
        entry.name if entry else skill_name,
        request=request,
        token=token,
        agent_id=resolved_agent_id,
        entry=entry,
    )
    allowed, entry, reason = mgr.runtime.can_load(
        skill_name,
        agent_id=resolved_agent_id,
        audit_metadata=_access_token_audit_metadata(request, token, resolved_agent_id),
    )
    return RuntimeCheckResponse(
        allowed=allowed,
        reason=reason,
        status=entry.status.value if entry else None,
        risk_level=entry.risk_level.value if entry and entry.risk_level else None,
    )


@runtime_router.post("/runtime/verify-skill-signature", response_model=VerifySkillSignatureResponse)
def token_runtime_verify_skill_signature(
    body: VerifySkillSignatureRequest,
    request: Request,
    x_agent_id: str | None = Header(None, alias="X-Agent-ID"),
    token: AccessToken = Depends(require_runtime_verify_token),
    db: Session = Depends(get_db),
    mgr: AgentManager = Depends(get_manager),
):
    resolved_agent_id = resolve_agent_id(body.agent_id, x_agent_id)
    agent = ensure_token_agent_allowed(db, token, resolved_agent_id)
    registry_entry = mgr.get_skill(body.skill_id or body.skill_name, include_scan_report=False) if (body.skill_id or body.skill_name) else None
    if registry_entry:
        _ensure_agent_skill_allowed_or_audit(
            mgr,
            agent,
            registry_entry.name,
            request=request,
            token=token,
            agent_id=resolved_agent_id,
            entry=registry_entry,
        )
    elif body.skill_name:
        _ensure_agent_skill_allowed_or_audit(
            mgr,
            agent,
            body.skill_name,
            request=request,
            token=token,
            agent_id=resolved_agent_id,
        )
    allowed, entry, reason = mgr.runtime.verify_local_signature(
        body.skill_name or "",
        body.local_signature,
        skill_id=body.skill_id,
        agent_id=resolved_agent_id,
        audit_metadata=_access_token_audit_metadata(request, token, resolved_agent_id),
    )
    return VerifySkillSignatureResponse(
        allowed=allowed,
        reason=reason,
        skill_id=entry.skill_id if entry else None,
        skill_name=entry.name if entry else (body.skill_name or ""),
        status=entry.status.value if entry else None,
        risk_level=entry.risk_level.value if entry and entry.risk_level else None,
        signature_match=allowed,
    )


@runtime_router.get("/runtime/check-tool", response_model=ToolCheckResponse)
def token_runtime_check_tool(
    request: Request,
    skill_name: str,
    tool_name: str,
    agent_id: str | None = None,
    x_agent_id: str | None = Header(None, alias="X-Agent-ID"),
    token: AccessToken = Depends(require_runtime_check_tool_token),
    db: Session = Depends(get_db),
    mgr: AgentManager = Depends(get_manager),
):
    resolved_agent_id = resolve_agent_id(agent_id, x_agent_id)
    agent = ensure_token_agent_allowed(db, token, resolved_agent_id)
    entry = mgr.get_skill(skill_name)
    _ensure_agent_skill_allowed_or_audit(
        mgr,
        agent,
        skill_name,
        request=request,
        token=token,
        agent_id=resolved_agent_id,
        entry=entry,
        event_type="tool_blocked",
        extra_details={"tool": tool_name},
    )
    allowed = mgr.runtime.check_tool(
        skill_name,
        tool_name,
        agent_id=resolved_agent_id,
        audit_metadata=_access_token_audit_metadata(request, token, resolved_agent_id),
    )
    return ToolCheckResponse(allowed=allowed, skill_name=skill_name, tool_name=tool_name)


@runtime_router.get("/runtime/can-load-prompt/{prompt_name}")
def token_runtime_can_load_prompt(
    prompt_name: str,
    agent_id: str | None = None,
    x_agent_id: str | None = Header(None, alias="X-Agent-ID"),
    token: AccessToken = Depends(require_runtime_can_load_token),
    db: Session = Depends(get_db),
    mgr: AgentManager = Depends(get_manager),
):
    resolved_agent_id = resolve_agent_id(agent_id, x_agent_id)
    agent = ensure_token_agent_allowed(db, token, resolved_agent_id)
    ensure_agent_prompt_allowed(agent, prompt_name)
    entry = mgr.get_prompt(prompt_name)
    if not entry:
        return {"allowed": False, "status": None, "reason": f"Prompt {prompt_name!r} not found in registry"}
    if not entry.is_loadable():
        return {"allowed": False, "status": entry.status.value, "reason": f"Prompt {prompt_name!r} is {entry.status.value}"}
    return {"allowed": True, "status": entry.status.value, "reason": "allowed"}


def _verify_bound_prompt(
    *,
    prompt_name: str,
    local_content: str | None,
    local_file_path: str | None,
    agent_id: str | None,
    x_agent_id: str | None,
    token: AccessToken,
    db: Session,
    mgr: AgentManager,
):
    resolved_agent_id = resolve_agent_id(agent_id, x_agent_id)
    agent = ensure_token_agent_allowed(db, token, resolved_agent_id)
    ensure_agent_prompt_allowed(agent, prompt_name)
    return mgr.verify_prompt_signature(
        prompt_name=prompt_name,
        local_content=local_content,
        local_file_path=Path(local_file_path) if local_file_path else None,
    )


@runtime_router.get("/runtime/verify-prompt")
def token_runtime_verify_prompt(
    prompt_name: str = Query(...),
    local_content: str | None = Query(None),
    local_file_path: str | None = Query(None),
    agent_id: str | None = Query(None),
    x_agent_id: str | None = Header(None, alias="X-Agent-ID"),
    token: AccessToken = Depends(require_runtime_verify_token),
    db: Session = Depends(get_db),
    mgr: AgentManager = Depends(get_manager),
):
    return _verify_bound_prompt(
        prompt_name=prompt_name,
        local_content=local_content,
        local_file_path=local_file_path,
        agent_id=agent_id,
        x_agent_id=x_agent_id,
        token=token,
        db=db,
        mgr=mgr,
    )


@runtime_router.post("/runtime/verify-prompt-signature")
def token_runtime_verify_prompt_signature(
    body: PromptVerifyPayload,
    agent_id: str | None = Query(None),
    x_agent_id: str | None = Header(None, alias="X-Agent-ID"),
    token: AccessToken = Depends(require_runtime_verify_token),
    db: Session = Depends(get_db),
    mgr: AgentManager = Depends(get_manager),
):
    return _verify_bound_prompt(
        prompt_name=body.prompt_name,
        local_content=body.local_content,
        local_file_path=body.local_file_path,
        agent_id=agent_id,
        x_agent_id=x_agent_id,
        token=token,
        db=db,
        mgr=mgr,
    )


@admin_router.get("/scanner/downloads", response_model=ScannerDownloadInfo)
def list_scanner_downloads():
    return ScannerDownloadInfo(items=_scanner_release_files())


@admin_router.get("/scanner/download")
def download_scanner(platform: str):
    if "/" in platform or "\\" in platform or ".." in platform:
        raise HTTPException(status_code=400, detail="Invalid scanner platform")
    filename = f"skill-scanner-{platform}"
    path = _scanner_release_dir() / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Scanner binary not found: scanner/releases/{filename}",
        )
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


def _download_skill_verifier_response():
    skill_dir = _skill_verifier_dir()
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail="Agent Skill Verifier 未找到")

    tmp = tempfile.NamedTemporaryFile(prefix="agent-manager-skill-verifier-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in skill_dir.rglob("*") if item.is_file()):
                rel = path.relative_to(skill_dir).as_posix()
                if "__pycache__" in rel.split("/") or rel.endswith(".pyc"):
                    continue
                archive.write(path, f"agent-manager-skill-verifier/{rel}")
        cleanup = BackgroundTasks()
        cleanup.add_task(tmp_path.unlink, missing_ok=True)
        return FileResponse(
            tmp_path,
            filename="agent-manager-skill-verifier.zip",
            media_type="application/zip",
            background=cleanup,
        )
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


@admin_router.get("/scanner/skill-verifier/download")
def download_skill_verifier():
    return _download_skill_verifier_response()


@admin_router.get("/scanner/skill-guard/download")
def download_skill_guard():
    return _download_skill_verifier_response()


@router.post("/scanner/imports", response_model=ScannerSubmitResponse)
@import_endpoint
def submit_scanner_import(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    manifest: str | None = Form(None),
    use_behavioral: bool = Form(False),
    use_llm: bool = Form(False),
    use_sandbox: bool = Form(False),
    use_skillspector: bool = Form(False),
    use_deep_scan: bool = Form(False),
    force_rescan: bool = Form(False),
    judgement_mode: str | None = Form(None),
    scanner_version: str | None = Form(None),
    host_id: str | None = Form(None),
    scanner_auth: ScannerAuthContext = Depends(require_scanner_submit_token),
    mgr: AgentManager = Depends(get_manager),
    store: ScannerTokenStore = Depends(get_token_store),
):
    if scanner_auth.access_token and scanner_auth.access_token.token_type == "client":
        if not host_id or scanner_auth.access_token.bound_client_id != host_id:
            raise HTTPException(status_code=403, detail="当前凭证未绑定此客户端，请先连接并注册")
    max_bytes = scanner_auth.max_upload_mb * 1024 * 1024
    if file.size and file.size > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (max {scanner_auth.max_upload_mb} MB)")

    parsed_manifest: dict[str, Any] | None = None
    if manifest:
        try:
            parsed_manifest = json.loads(manifest)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid manifest JSON: {exc}") from exc
        if not isinstance(parsed_manifest, dict):
            raise HTTPException(status_code=400, detail="Invalid manifest JSON: expected an object")
        if not str(parsed_manifest.get("name") or "").strip():
            raise HTTPException(
                status_code=400,
                detail="SKILL.md 缺少 name 字段（格式：name: your-skill-name）",
            )

    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-manager-scanner-"))
    try:
        zip_path = tmp_dir / "skill.zip"
        content = file.file.read()
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large (max {scanner_auth.max_upload_mb} MB)")
        zip_path.write_bytes(content)

        extract_dir = tmp_dir / "skill"
        _extract_zip_with_nested_archives(zip_path, extract_dir)
        skill_root = _resolve_skill_root(extract_dir)
        try:
            skill_name, _, _, _ = _load_manifest(skill_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        server_manifest = _fingerprint_skill_dir(skill_root)
        if parsed_manifest and parsed_manifest.get("fingerprint") != server_manifest["fingerprint"]:
            raise HTTPException(
                status_code=400,
                detail="Manifest fingerprint mismatch between scanner and server",
            )
        if force_rescan:
            existing = mgr.registry.find_version_by_content(skill_name, compute_content_fingerprint(skill_root))
            if existing is not None:
                same_bound_client = bool(
                    scanner_auth.access_token
                    and scanner_auth.access_token.token_type == "client"
                    and scanner_auth.access_token.bound_client_id == host_id
                )
                if not same_bound_client and not _submission_owned_by(scanner_auth, existing):
                    raise HTTPException(status_code=403, detail="scanner token can only rescan own submissions")

        persistent_dir = mgr.registry.data_dir / "scanner_uploaded_skills" / uuid.uuid4().hex
        persistent_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_root, persistent_dir)

        source = SourceInfo(
            origin=SkillOrigin.LOCAL,
            author=scanner_auth.author or scanner_auth.name,
            channel="agent_manager_client" if scanner_auth.access_token and scanner_auth.access_token.token_type == "client" else "scanner",
            token_name=scanner_auth.token_name,
        )
        deep_scan_enabled = use_deep_scan or use_skillspector
        response = _submit_directory_for_processing(
            mgr,
            background_tasks,
            persistent_dir,
            source,
            use_behavioral,
            use_llm,
            use_sandbox,
            deep_scan_enabled,
            judgement_mode,
            entry_prepared=lambda entry: _grant_submission_access(mgr, scanner_auth, entry),
        )
        if force_rescan and response.scan_state == "REUSED":
            entry = mgr.get_skill(response.version_id)
            if entry is None or not _submission_owned_by(scanner_auth, entry):
                raise HTTPException(status_code=403, detail="scanner token can only rescan own submissions")
            entry, started = mgr.request_rescan(entry.skill_id, scan_options={
                "use_behavioral": use_behavioral,
                "use_llm": use_llm,
                "use_sandbox": use_sandbox,
                "use_skillspector": deep_scan_enabled,
            })
            if started:
                _scan_executor.submit(
                    _process_pending_submission_task,
                    mgr,
                    entry.skill_id,
                    use_behavioral,
                    use_llm,
                    use_sandbox,
                    deep_scan_enabled,
                    True,
                    judgement_mode,
                )
            active_run = next((run for run in mgr.list_scan_runs(entry.skill_id) if run.status == "PENDING"), None)
            response.scan_reused = False
            response.scan_run_id = active_run.scan_run_id if active_run else None
            response.scan_state = "PENDING"
            response.status = "PENDING"
            response.outcome = "rescan_submitted" if started else "scan_in_progress"
            response.risk_level = None
            response.findings_count = 0
            response.message = "已重新检测现有版本。" if started else "相同内容版本正在检测，已复用现有任务。"
        store.log_event(
            "scanner_import_submitted",
            scanner_auth.legacy_token,
            actor=scanner_auth.name if scanner_auth.access_token else None,
            details={
                "skill_id": response.skill_id,
                "skill_name": response.name,
                "host_id": host_id,
                "scanner_version": scanner_version,
                "manifest_fingerprint": (parsed_manifest or {}).get("fingerprint") if parsed_manifest else None,
                "server_fingerprint": server_manifest["fingerprint"],
                "force_rescan": force_rescan,
                "detection_options": {
                    "rules": use_behavioral,
                    "deep_scan": deep_scan_enabled,
                    "sandbox": use_sandbox,
                    "llm": use_llm,
                    "scan_result_reuse": mgr.policy.scan_result_reuse_enabled,
                },
            },
        )
        return ScannerSubmitResponse(**response.model_dump(), detail_url=f"/skills/{response.skill_id}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/scanner/imports/{skill_id}")
def get_scanner_import(
    skill_id: str,
    scanner_auth: ScannerAuthContext = Depends(require_scanner_read_token),
    mgr: AgentManager = Depends(get_manager),
):
    entry = mgr.get_skill(skill_id, include_scan_report=False)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not _submission_owned_by(scanner_auth, entry):
        raise HTTPException(status_code=403, detail="scanner token can only read own submissions")
    payload = entry.model_dump(
        mode="json",
        exclude={"vetting": {"scan_report"}, "submission_principals": True},
    )
    payload["skill_id"] = entry.family_id or entry.skill_id
    payload["version_id"] = entry.skill_id
    active_runs = [run for run in mgr.list_scan_runs(entry.skill_id) if run.status == "PENDING"]
    scan_pending = bool(active_runs)
    payload["scan_pending"] = scan_pending
    if active_runs:
        run = max(active_runs, key=lambda item: item.started_at)
        payload["scan_progress_stage"] = run.result.get("progress_stage", "queued")
        payload["scan_progress_analyzers"] = run.result.get("analyzers", {})
    if scan_pending:
        # A rescan intentionally preserves the previous effective decision
        # until it completes. Scanner clients, however, must observe the job
        # state so they do not auto-install an old APPROVED result mid-scan.
        payload["effective_status"] = entry.status.value
        payload["status"] = SkillStatus.PENDING.value
    return payload
