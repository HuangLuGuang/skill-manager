"""
FastAPI router for the skill manager API.

Provides endpoints for CI/CD pipelines, agent runtimes, and review UIs.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from skill_manager.core.llm import LLMConfig
from skill_manager.core.manager import SkillManager
from skill_manager.core.models import SkillStatus, SourceInfo, SkillOrigin
from skill_manager.core.policy import CompanyPolicy
from skill_manager.core.registry import Registry

router = APIRouter(prefix="/api/v1", tags=["skill-manager"])

# Module-level singleton (overridable in tests via dependency injection)
_manager: SkillManager | None = None


def _discover_policy_path() -> Path | None:
    for candidate in (Path("company-policy.yaml"), Path.home() / ".skill-manager" / "policy.yaml"):
        if candidate.exists():
            return candidate.resolve()
    return None


def get_manager() -> SkillManager:
    global _manager
    if _manager is None:
        policy_path = _discover_policy_path()
        policy = CompanyPolicy.load(policy_path) if policy_path else CompanyPolicy.default()
        _manager = SkillManager(policy=policy)
    return _manager


def _policy_path_for_write() -> Path:
    existing = _discover_policy_path()
    if existing:
        return existing
    target = Path.home() / ".skill-manager" / "policy.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _resolve_skill_root(extract_dir: Path) -> Path:
    if (extract_dir / "SKILL.md").exists():
        return extract_dir

    matches = sorted(path.parent for path in extract_dir.rglob("SKILL.md"))
    unique_matches: list[Path] = []
    seen: set[str] = set()
    for path in matches:
        key = str(path.resolve())
        if key not in seen:
            unique_matches.append(path)
            seen.add(key)

    if len(unique_matches) == 1:
        return unique_matches[0]

    if not unique_matches:
        raise HTTPException(status_code=400, detail="SKILL.md not found in uploaded ZIP")

    raise HTTPException(
        status_code=400,
        detail="Multiple SKILL.md files found in uploaded ZIP; package must contain exactly one skill",
    )


# --------------------------------------------------------------------------- #
# Request / Response schemas                                                    #
# --------------------------------------------------------------------------- #

class SubmitResponse(BaseModel):
    skill_id: str
    name: str
    status: str
    risk_level: str | None
    findings_count: int
    message: str


class ApproveRequest(BaseModel):
    approver: str
    note: str | None = None


class RejectRequest(BaseModel):
    reviewer: str
    reason: str


class RetireRequest(BaseModel):
    reason: str
    actor: str | None = None


class RuntimeCheckResponse(BaseModel):
    allowed: bool
    reason: str
    status: str | None = None
    risk_level: str | None = None


class ToolCheckResponse(BaseModel):
    allowed: bool
    skill_name: str
    tool_name: str


class VerifySkillSignatureRequest(BaseModel):
    skill_name: str
    local_signature: str
    skill_id: str | None = None
    agent_id: str | None = None


class VerifySkillSignatureResponse(BaseModel):
    allowed: bool
    reason: str
    skill_id: str | None = None
    skill_name: str
    status: str | None = None
    risk_level: str | None = None
    signature_match: bool


class PolicyPayload(BaseModel):
    auto_approve_max_risk: str
    require_human_review: list[str]
    auto_reject_risk: list[str]
    blocked_permissions: list[str]
    trusted_authors: list[str]
    allowed_tools_allowlist: list[str]
    max_allowed_tools: int
    require_license: bool
    accepted_licenses: list[str]
    scanner_policy: str


class PolicyResponse(BaseModel):
    policy_path: str | None
    policy: PolicyPayload


class SystemStatusResponse(BaseModel):
    data_dir: str
    policy_path: str | None
    registry_entries: int
    review_queue: int
    signing_key_configured: bool
    scanner_available: bool
    hooks_available: bool
    llm_enabled: bool
    llm_provider: str
    llm_api_base: str
    llm_model: str
    llm_api_key_configured: bool
    scan_mode: str
    service: str


class LLMConfigPayload(BaseModel):
    enabled: bool = False
    provider: str = "deepseek"
    api_base: str = "https://api.deepseek.com"
    api_key: str | None = None
    model: str = "deepseek-chat"
    timeout_seconds: float = 30.0
    max_files: int = 6
    max_file_chars: int = 3000
    max_manifest_chars: int = 12000
    clear_api_key: bool = False


class LLMConfigResponse(BaseModel):
    config_path: str
    enabled: bool
    provider: str
    api_base: str
    model: str
    timeout_seconds: float
    max_files: int
    max_file_chars: int
    max_manifest_chars: int
    api_key_configured: bool
    api_key_masked: str | None = None


class VerifySignatureRequest(BaseModel):
    skill_path: str | None = None


class VerifySignatureResponse(BaseModel):
    valid: bool
    skill_id: str
    skill_name: str
    reason: str


class SkillContentResponse(BaseModel):
    skill_id: str
    skill_name: str
    manifest_path: str
    content: str


class SkillFileEntry(BaseModel):
    path: str
    size_bytes: int
    modified_at: str


class SkillFilesResponse(BaseModel):
    skill_id: str
    skill_name: str
    skill_path: str
    file_count: int
    files: list[SkillFileEntry]


class SkillFileContentResponse(BaseModel):
    skill_id: str
    skill_name: str
    path: str
    absolute_path: str
    content: str


def _paginate(items: list[Any], page: int, page_size: int) -> dict[str, Any]:
    total = len(items)
    start = max(page - 1, 0) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# --------------------------------------------------------------------------- #
# Health                                                                        #
# --------------------------------------------------------------------------- #

@router.get("/health")
def health():
    return {"status": "ok", "service": "skill-manager"}


@router.get("/policy", response_model=PolicyResponse)
def get_policy(mgr: SkillManager = Depends(get_manager)):
    policy_path = _discover_policy_path()
    return PolicyResponse(
        policy_path=str(policy_path) if policy_path else None,
        policy=PolicyPayload(**mgr.policy.to_dict()),
    )


@router.get("/llm-config", response_model=LLMConfigResponse)
def get_llm_config():
    config = LLMConfig.load()
    public = config.public_dict()
    return LLMConfigResponse(**public)


@router.put("/llm-config", response_model=LLMConfigResponse)
def update_llm_config(body: LLMConfigPayload):
    current = LLMConfig.load()
    data = body.model_dump()
    clear_api_key = data.pop("clear_api_key", False)
    incoming_api_key = data.pop("api_key", None)
    merged = {**current.model_dump(), **data}
    if clear_api_key:
        merged["api_key"] = None
    elif incoming_api_key:
        merged["api_key"] = incoming_api_key
    else:
        merged["api_key"] = current.api_key

    config = LLMConfig.model_validate(merged)
    path = config.save()
    public = config.public_dict()
    public["config_path"] = str(path)
    return LLMConfigResponse(**public)


@router.put("/policy", response_model=PolicyResponse)
def update_policy(body: PolicyPayload):
    global _manager
    path = _policy_path_for_write()
    policy = CompanyPolicy(body.model_dump())
    policy.save(path)
    _manager = SkillManager(policy=policy)
    return PolicyResponse(policy_path=str(path), policy=body)


@router.get("/system/status", response_model=SystemStatusResponse)
def get_system_status():
    mgr = get_manager()
    registry = Registry(mgr.registry.data_dir)
    llm_config = LLMConfig.load()
    try:
        import skill_scanner  # noqa: F401
        scanner_available = True
    except Exception:
        scanner_available = False

    if scanner_available and llm_config.enabled:
        scan_mode = "scanner + llm"
    elif scanner_available:
        scan_mode = "scanner only"
    elif llm_config.enabled:
        scan_mode = "llm only"
    else:
        scan_mode = "manifest only"

    return SystemStatusResponse(
        data_dir=str(mgr.registry.data_dir),
        policy_path=str(_discover_policy_path()) if _discover_policy_path() else None,
        registry_entries=len(registry.list_all()),
        review_queue=len(registry.list_review_queue()),
        signing_key_configured=bool(os.environ.get("SKILL_MANAGER_SIGNING_KEY", "").strip()),
        scanner_available=scanner_available,
        hooks_available=(Path(__file__).resolve().parent.parent / "hooks" / "agent_hook.py").exists(),
        llm_enabled=llm_config.enabled,
        llm_provider=llm_config.provider,
        llm_api_base=llm_config.api_base,
        llm_model=llm_config.model,
        llm_api_key_configured=bool(llm_config.api_key),
        scan_mode=scan_mode,
        service="skill-manager",
    )


# --------------------------------------------------------------------------- #
# Submit                                                                        #
# --------------------------------------------------------------------------- #

@router.post("/skills/submit-zip", response_model=SubmitResponse)
async def submit_skill_zip(
    file: UploadFile = File(...),
    author: str | None = Query(None),
    origin: str = Query("unknown"),
    use_behavioral: bool = Query(False),
    use_llm: bool = Query(False),
    mgr: SkillManager = Depends(get_manager),
):
    """
    Submit a skill package as a ZIP file for vetting.

    The ZIP must contain a SKILL.md at its root.
    """
    if file.size and file.size > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    tmp_dir = Path(tempfile.mkdtemp(prefix="skill-manager-"))
    try:
        zip_path = tmp_dir / "skill.zip"
        with open(zip_path, "wb") as f:
            content = await file.read()
            f.write(content)

        import zipfile
        extract_dir = tmp_dir / "skill"
        with zipfile.ZipFile(zip_path) as zf:
            # Security: check for path traversal
            for name in zf.namelist():
                if ".." in name or name.startswith("/"):
                    raise HTTPException(status_code=400, detail=f"Unsafe path in ZIP: {name}")
            zf.extractall(extract_dir)

        skill_root = _resolve_skill_root(extract_dir)

        persistent_dir = mgr.registry.data_dir / "uploaded_skills" / uuid.uuid4().hex
        persistent_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_root, persistent_dir)

        source = SourceInfo(origin=SkillOrigin(origin), author=author)

        entry = mgr.submit(
            persistent_dir,
            source=source,
            use_behavioral=use_behavioral,
            use_llm=use_llm,
        )

        msg = {
            "APPROVED": "Auto-approved. Call /deploy to activate.",
            "VETTED": "Queued for human review.",
            "REJECTED": "Rejected by policy.",
        }.get(entry.status.value, entry.status.value)

        return SubmitResponse(
            skill_id=entry.skill_id,
            name=entry.name,
            status=entry.status.value,
            risk_level=entry.risk_level.value if entry.risk_level else None,
            findings_count=entry.vetting.findings_count if entry.vetting else 0,
            message=msg,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Registry                                                                      #
# --------------------------------------------------------------------------- #

@router.get("/skills")
def list_skills(
    status: str | None = Query(None),
    loadable_only: bool = Query(False),
    risk_level: str | None = Query(None),
    q: str | None = Query(None),
    sort_by: str = Query("submitted_at"),
    sort_order: str = Query("desc"),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    mgr: SkillManager = Depends(get_manager),
):
    """List skills, optionally filtered by status."""
    s = SkillStatus(status) if status else None
    entries = mgr.list_skills(s)
    if loadable_only:
        entries = [e for e in entries if e.is_loadable()]

    if risk_level:
        entries = [e for e in entries if e.risk_level and e.risk_level.value == risk_level]

    if q:
        needle = q.lower()
        entries = [
            e for e in entries
            if needle in e.name.lower()
            or needle in e.skill_id.lower()
            or needle in (e.approved_by or "").lower()
        ]

    reverse = sort_order.lower() != "asc"
    if sort_by == "name":
        entries = sorted(entries, key=lambda e: e.name.lower(), reverse=reverse)
    elif sort_by == "skill_id":
        entries = sorted(entries, key=lambda e: e.skill_id.lower(), reverse=reverse)
    elif sort_by == "status":
        entries = sorted(entries, key=lambda e: e.status.value, reverse=reverse)
    elif sort_by == "risk_level":
        entries = sorted(entries, key=lambda e: e.risk_level.value if e.risk_level else "", reverse=reverse)
    elif sort_by == "approved_by":
        entries = sorted(entries, key=lambda e: (e.approved_by or "").lower(), reverse=reverse)
    else:
        entries = sorted(entries, key=lambda e: e.submitted_at, reverse=reverse)

    summaries = [e.summary() for e in entries]
    if page is not None or page_size is not None:
        return _paginate(summaries, page or 1, page_size or 10)
    return summaries


@router.get("/skills/{skill_id_or_name}")
def get_skill(skill_id_or_name: str, mgr: SkillManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return entry.model_dump(mode="json", exclude={"vetting": {"scan_report"}})


@router.get("/skills/{skill_id_or_name}/scan-report")
def get_scan_report(skill_id_or_name: str, mgr: SkillManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "skill_id": entry.skill_id,
        "name": entry.name,
        "scan_report": entry.vetting.scan_report if entry.vetting else {},
    }


@router.get("/skills/{skill_id_or_name}/content", response_model=SkillContentResponse)
def get_skill_content(skill_id_or_name: str, mgr: SkillManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.skill_path:
        raise HTTPException(status_code=400, detail="Skill path is not available")

    manifest_path = Path(entry.skill_path) / "SKILL.md"
    if not manifest_path.exists() or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="SKILL.md not found")

    try:
        content = manifest_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read SKILL.md: {exc}") from exc

    return SkillContentResponse(
        skill_id=entry.skill_id,
        skill_name=entry.name,
        manifest_path=str(manifest_path),
        content=content,
    )


@router.get("/skills/{skill_id_or_name}/files", response_model=SkillFilesResponse)
def list_skill_files(skill_id_or_name: str, mgr: SkillManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.skill_path:
        raise HTTPException(status_code=400, detail="Skill path is not available")

    skill_root = Path(entry.skill_path)
    if not skill_root.exists() or not skill_root.is_dir():
        raise HTTPException(status_code=404, detail="Skill directory not found")

    files = [
        SkillFileEntry(
            path=str(path.relative_to(skill_root).as_posix()),
            size_bytes=path.stat().st_size,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        )
        for path in sorted(skill_root.rglob("*"))
        if path.is_file()
    ]

    return SkillFilesResponse(
        skill_id=entry.skill_id,
        skill_name=entry.name,
        skill_path=str(skill_root),
        file_count=len(files),
        files=files,
    )


@router.get("/skills/{skill_id_or_name}/file-content", response_model=SkillFileContentResponse)
def get_skill_file_content(
    skill_id_or_name: str,
    path: str = Query(..., min_length=1),
    mgr: SkillManager = Depends(get_manager),
):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.skill_path:
        raise HTTPException(status_code=400, detail="Skill path is not available")

    skill_root = Path(entry.skill_path).resolve()
    if not skill_root.exists() or not skill_root.is_dir():
        raise HTTPException(status_code=404, detail="Skill directory not found")

    requested = (skill_root / path).resolve()
    try:
        requested.relative_to(skill_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsafe file path") from exc

    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        content = requested.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File is not a UTF-8 text file")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}") from exc

    return SkillFileContentResponse(
        skill_id=entry.skill_id,
        skill_name=entry.name,
        path=path,
        absolute_path=str(requested),
        content=content,
    )


@router.post("/skills/{skill_id_or_name}/verify-signature", response_model=VerifySignatureResponse)
def verify_skill_signature(
    skill_id_or_name: str,
    body: VerifySignatureRequest,
    mgr: SkillManager = Depends(get_manager),
):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not entry.signature:
        return VerifySignatureResponse(
            valid=False,
            skill_id=entry.skill_id,
            skill_name=entry.name,
            reason="No signature stored for this skill",
        )

    skill_path = body.skill_path or entry.skill_path
    if not skill_path:
        return VerifySignatureResponse(
            valid=False,
            skill_id=entry.skill_id,
            skill_name=entry.name,
            reason="No skill path available for verification",
        )

    from skill_manager.core.signer import verify_signature

    valid = verify_signature(skill_path, entry.signature)
    return VerifySignatureResponse(
        valid=valid,
        skill_id=entry.skill_id,
        skill_name=entry.name,
        reason="signature valid" if valid else "signature mismatch",
    )


# --------------------------------------------------------------------------- #
# Review                                                                        #
# --------------------------------------------------------------------------- #

@router.get("/review")
def list_review_queue(
    risk_level: str | None = Query(None),
    q: str | None = Query(None),
    sort_by: str = Query("queued_at"),
    sort_order: str = Query("asc"),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    mgr: SkillManager = Depends(get_manager),
):
    queue = mgr.list_review_queue()

    if risk_level:
        queue = [r for r in queue if r.risk_level.value == risk_level]

    if q:
        needle = q.lower()
        queue = [
            r for r in queue
            if needle in r.skill_name.lower()
            or needle in r.skill_id.lower()
            or needle in (r.notes or "").lower()
        ]

    reverse = sort_order.lower() != "asc"
    if sort_by == "skill_name":
        queue = sorted(queue, key=lambda r: r.skill_name.lower(), reverse=reverse)
    elif sort_by == "risk_level":
        queue = sorted(queue, key=lambda r: r.risk_level.value, reverse=reverse)
    elif sort_by == "submitted_at":
        queue = sorted(queue, key=lambda r: r.submitted_at, reverse=reverse)
    else:
        queue = sorted(queue, key=lambda r: r.queued_at, reverse=reverse)

    data = [r.model_dump(mode="json") for r in queue]
    if page is not None or page_size is not None:
        return _paginate(data, page or 1, page_size or 10)
    return data


@router.post("/skills/{skill_id}/approve")
def approve_skill(
    skill_id: str,
    body: ApproveRequest,
    mgr: SkillManager = Depends(get_manager),
):
    try:
        entry = mgr.approve(skill_id, approver=body.approver, note=body.note)
        return {"skill_id": entry.skill_id, "status": entry.status.value, "message": "Approved"}
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{skill_id}/reject")
def reject_skill(
    skill_id: str,
    body: RejectRequest,
    mgr: SkillManager = Depends(get_manager),
):
    try:
        entry = mgr.reject(skill_id, reviewer=body.reviewer, reason=body.reason)
        return {"skill_id": entry.skill_id, "status": entry.status.value, "message": "Rejected"}
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# --------------------------------------------------------------------------- #
# Deploy / Retire                                                               #
# --------------------------------------------------------------------------- #

@router.post("/skills/{skill_id}/deploy")
def deploy_skill(skill_id: str, mgr: SkillManager = Depends(get_manager)):
    try:
        entry = mgr.deploy(skill_id)
        return {"skill_id": entry.skill_id, "status": entry.status.value, "message": "Deployed"}
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/{skill_id}/retire")
def retire_skill(
    skill_id: str,
    body: RetireRequest,
    mgr: SkillManager = Depends(get_manager),
):
    try:
        entry = mgr.retire(skill_id, reason=body.reason, actor=body.actor)
        return {"skill_id": entry.skill_id, "status": entry.status.value, "message": "Retired"}
    except (KeyError) as e:
        raise HTTPException(status_code=404, detail=str(e))


# --------------------------------------------------------------------------- #
# Runtime guard endpoints (called by agents)                                    #
# --------------------------------------------------------------------------- #

@router.get("/runtime/can-load/{skill_name}", response_model=RuntimeCheckResponse)
def runtime_can_load(
    skill_name: str,
    skill_path: str | None = Query(None),
    agent_id: str | None = Query(None),
    mgr: SkillManager = Depends(get_manager),
):
    """Check whether an agent may load a skill (enforces registry + signature)."""
    allowed, entry, reason = mgr.runtime.can_load(
        skill_name, skill_path=skill_path, agent_id=agent_id
    )
    return RuntimeCheckResponse(
        allowed=allowed,
        reason=reason,
        status=entry.status.value if entry else None,
        risk_level=entry.risk_level.value if entry and entry.risk_level else None,
    )


@router.post("/runtime/verify-skill-signature", response_model=VerifySkillSignatureResponse)
def runtime_verify_skill_signature(
    body: VerifySkillSignatureRequest,
    mgr: SkillManager = Depends(get_manager),
):
    """Verify a locally computed skill signature sent by an external agent."""
    allowed, entry, reason = mgr.runtime.verify_local_signature(
        body.skill_name,
        body.local_signature,
        skill_id=body.skill_id,
        agent_id=body.agent_id,
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


@router.get("/runtime/check-tool", response_model=ToolCheckResponse)
def runtime_check_tool(
    skill_name: str = Query(...),
    tool_name: str = Query(...),
    agent_id: str | None = Query(None),
    mgr: SkillManager = Depends(get_manager),
):
    """Check whether a skill is permitted to invoke a tool."""
    allowed = mgr.runtime.check_tool(skill_name, tool_name, agent_id=agent_id)
    return ToolCheckResponse(allowed=allowed, skill_name=skill_name, tool_name=tool_name)


# --------------------------------------------------------------------------- #
# Hook endpoints (called by claude_api_hook.py)                                #
# --------------------------------------------------------------------------- #

class HookEventRequest(BaseModel):
    hook_event_name: str
    session_id: str | None = None
    cwd: str | None = None
    file_path: str | None = None
    source: str | None = None
    tool_name: str | None = None
    # Allow any other fields from the hook event
    model_config = {"extra": "allow"}


class HookEventResponse(BaseModel):
    allowed: bool
    message: str


@router.post("/hook/event", response_model=HookEventResponse)
def hook_process_event(
    body: HookEventRequest,
    mgr: SkillManager = Depends(get_manager),
):
    """Process a Claude Code hook event via API."""
    from skill_manager.hooks.agent_hook import process_event

    # Convert the model to a dict, preserving all extra fields
    event = body.model_dump()
    allowed, message = process_event(event)
    return HookEventResponse(allowed=allowed, message=message)


# --------------------------------------------------------------------------- #
# Audit                                                                         #
# --------------------------------------------------------------------------- #

@router.get("/audit")
def get_audit(
    since_hours: float = Query(24.0),
    skill_id: str | None = Query(None),
    event_type: str | None = Query(None),
    actor: str | None = Query(None),
    q: str | None = Query(None),
    sort_order: str = Query("desc"),
    limit: int = Query(100),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    mgr: SkillManager = Depends(get_manager),
):
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    events = mgr.audit(since=since, skill_id=skill_id, limit=limit)
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    if actor:
        needle = actor.lower()
        events = [e for e in events if needle in (e.actor or "").lower()]
    if q:
        needle = q.lower()
        events = [
            e for e in events
            if needle in e.skill_name.lower()
            or needle in e.skill_id.lower()
            or needle in (e.actor or "").lower()
        ]

    events = sorted(events, key=lambda e: e.timestamp, reverse=(sort_order.lower() != "asc"))
    data = [e.model_dump(mode="json") for e in events]
    if page is not None or page_size is not None:
        return _paginate(data, page or 1, page_size or 10)
    return data
