"""Scanner-facing API with dedicated scanner token authentication."""

from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent_manager.api.router import (
    RuntimeCheckResponse,
    SubmitResponse,
    ToolCheckResponse,
    VerifySkillSignatureRequest,
    VerifySkillSignatureResponse,
    _extract_zip_with_nested_archives,
    _resolve_skill_root,
    _submit_directory_for_processing,
    get_manager,
)
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import SkillOrigin, SourceInfo
from agent_manager.core.scanner_tokens import DEFAULT_SCOPES, ScannerToken, ScannerTokenStore
from backend.models import AccessToken
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


def _fingerprint_skill_dir(skill_dir: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(item for item in skill_dir.rglob("*") if item.is_file()):
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


def _skill_guard_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "demo" / "agent-manager-skill-guard" / "skills" / "agent-manager-skill-guard"


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
) -> ScannerToken:
    return _validate_scanner_token("scanner:submit", request, authorization, store)


def require_scanner_read_token(
    request: Request,
    authorization: str | None = Header(None),
    store: ScannerTokenStore = Depends(get_token_store),
) -> ScannerToken:
    return _validate_scanner_token("scanner:read-own-results", request, authorization, store)


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
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Token name is required")
    try:
        record, plain = store.create(
            name=body.name,
            scopes=body.scopes,
            expires_at=body.expires_at,
            allowed_ips=body.allowed_ips,
            max_upload_mb=body.max_upload_mb,
            max_concurrent_jobs=body.max_concurrent_jobs,
            created_by=body.created_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ScannerTokenCreateResponse(token=plain, record=record.public_dict())


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
    ensure_agent_skill_allowed(agent, skill_name)
    allowed, entry, reason = mgr.runtime.can_load(skill_name, agent_id=resolved_agent_id)
    return RuntimeCheckResponse(
        allowed=allowed,
        reason=reason,
        status=entry.status.value if entry else None,
        risk_level=entry.risk_level.value if entry and entry.risk_level else None,
    )


@runtime_router.post("/runtime/verify-skill-signature", response_model=VerifySkillSignatureResponse)
def token_runtime_verify_skill_signature(
    body: VerifySkillSignatureRequest,
    x_agent_id: str | None = Header(None, alias="X-Agent-ID"),
    token: AccessToken = Depends(require_runtime_verify_token),
    db: Session = Depends(get_db),
    mgr: AgentManager = Depends(get_manager),
):
    resolved_agent_id = resolve_agent_id(body.agent_id, x_agent_id)
    agent = ensure_token_agent_allowed(db, token, resolved_agent_id)
    ensure_agent_skill_allowed(agent, body.skill_name)
    allowed, entry, reason = mgr.runtime.verify_local_signature(
        body.skill_name,
        body.local_signature,
        skill_id=body.skill_id,
        agent_id=resolved_agent_id,
    )
    return VerifySkillSignatureResponse(
        allowed=allowed,
        reason=reason,
        skill_id=entry.skill_id if entry else None,
        skill_name=entry.name if entry else body.skill_name,
        status=entry.status.value if entry else None,
        risk_level=entry.risk_level.value if entry and entry.risk_level else None,
        signature_match=allowed,
    )


@runtime_router.get("/runtime/check-tool", response_model=ToolCheckResponse)
def token_runtime_check_tool(
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
    ensure_agent_skill_allowed(agent, skill_name)
    allowed = mgr.runtime.check_tool(skill_name, tool_name, agent_id=resolved_agent_id)
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


@admin_router.get("/scanner/skill-guard/download")
def download_skill_guard():
    skill_dir = _skill_guard_dir()
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail="Agent Manager Skill Guard demo not found")

    tmp = tempfile.NamedTemporaryFile(prefix="agent-manager-skill-guard-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in skill_dir.rglob("*") if item.is_file()):
                rel = path.relative_to(skill_dir).as_posix()
                if "__pycache__" in rel.split("/") or rel.endswith(".pyc"):
                    continue
                archive.write(path, f"agent-manager-skill-guard/{rel}")
        cleanup = BackgroundTasks()
        cleanup.add_task(tmp_path.unlink, missing_ok=True)
        return FileResponse(
            tmp_path,
            filename="agent-manager-skill-guard.zip",
            media_type="application/zip",
            background=cleanup,
        )
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


@router.post("/scanner/imports", response_model=ScannerSubmitResponse)
async def submit_scanner_import(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    manifest: str | None = Form(None),
    use_behavioral: bool = Form(False),
    use_llm: bool = Form(False),
    use_sandbox: bool = Form(False),
    scanner_version: str | None = Form(None),
    host_id: str | None = Form(None),
    scanner_token: ScannerToken = Depends(require_scanner_submit_token),
    mgr: AgentManager = Depends(get_manager),
    store: ScannerTokenStore = Depends(get_token_store),
):
    max_bytes = scanner_token.max_upload_mb * 1024 * 1024
    if file.size and file.size > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (max {scanner_token.max_upload_mb} MB)")

    parsed_manifest: dict[str, Any] | None = None
    if manifest:
        try:
            parsed_manifest = json.loads(manifest)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid manifest JSON: {exc}") from exc

    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-manager-scanner-"))
    try:
        zip_path = tmp_dir / "skill.zip"
        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File too large (max {scanner_token.max_upload_mb} MB)")
        zip_path.write_bytes(content)

        extract_dir = tmp_dir / "skill"
        _extract_zip_with_nested_archives(zip_path, extract_dir)
        skill_root = _resolve_skill_root(extract_dir)
        server_manifest = _fingerprint_skill_dir(skill_root)
        if parsed_manifest and parsed_manifest.get("fingerprint") != server_manifest["fingerprint"]:
            raise HTTPException(
                status_code=400,
                detail="Manifest fingerprint mismatch between scanner and server",
            )

        persistent_dir = mgr.registry.data_dir / "scanner_uploaded_skills" / uuid.uuid4().hex
        persistent_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_root, persistent_dir)

        source = SourceInfo(
            origin=SkillOrigin.LOCAL,
            author=scanner_token.name,
            version=scanner_version,
        )
        response = _submit_directory_for_processing(
            mgr,
            background_tasks,
            persistent_dir,
            source,
            use_behavioral,
            use_llm,
            use_sandbox,
        )
        store.log_event(
            "scanner_import_submitted",
            scanner_token,
            details={
                "skill_id": response.skill_id,
                "skill_name": response.name,
                "host_id": host_id,
                "scanner_version": scanner_version,
                "manifest_fingerprint": (parsed_manifest or {}).get("fingerprint") if parsed_manifest else None,
                "server_fingerprint": server_manifest["fingerprint"],
            },
        )
        return ScannerSubmitResponse(**response.model_dump(), detail_url=f"/skills/{response.skill_id}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/scanner/imports/{skill_id}")
def get_scanner_import(
    skill_id: str,
    scanner_token: ScannerToken = Depends(require_scanner_read_token),
    mgr: AgentManager = Depends(get_manager),
):
    entry = mgr.get_skill(skill_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if entry.source.author != scanner_token.name:
        raise HTTPException(status_code=403, detail="scanner token can only read own submissions")
    return entry.model_dump(mode="json", exclude={"vetting": {"scan_report"}})
