"""
FastAPI router for the skill manager API.

Provides endpoints for CI/CD pipelines, agent runtimes, and review UIs.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from skill_manager.core.manager import SkillManager
from skill_manager.core.models import SkillStatus, SourceInfo, SkillOrigin

router = APIRouter(prefix="/api/v1", tags=["skill-manager"])

# Module-level singleton (overridable in tests via dependency injection)
_manager: SkillManager | None = None


def get_manager() -> SkillManager:
    global _manager
    if _manager is None:
        _manager = SkillManager()
    return _manager


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


# --------------------------------------------------------------------------- #
# Health                                                                        #
# --------------------------------------------------------------------------- #

@router.get("/health")
def health():
    return {"status": "ok", "service": "skill-manager"}


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

        source = SourceInfo(origin=SkillOrigin(origin), author=author)

        entry = mgr.submit(
            extract_dir,
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
    mgr: SkillManager = Depends(get_manager),
):
    """List skills, optionally filtered by status."""
    s = SkillStatus(status) if status else None
    return [e.summary() for e in mgr.list_skills(s)]


@router.get("/skills/{skill_id_or_name}")
def get_skill(skill_id_or_name: str, mgr: SkillManager = Depends(get_manager)):
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return entry.model_dump(mode="json", exclude={"vetting": {"scan_report"}})


# --------------------------------------------------------------------------- #
# Review                                                                        #
# --------------------------------------------------------------------------- #

@router.get("/review")
def list_review_queue(mgr: SkillManager = Depends(get_manager)):
    return [r.model_dump(mode="json") for r in mgr.list_review_queue()]


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
# Audit                                                                         #
# --------------------------------------------------------------------------- #

@router.get("/audit")
def get_audit(
    since_hours: float = Query(24.0),
    skill_id: str | None = Query(None),
    limit: int = Query(100),
    mgr: SkillManager = Depends(get_manager),
):
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    events = mgr.audit(since=since, skill_id=skill_id, limit=limit)
    return [e.model_dump(mode="json") for e in events]
