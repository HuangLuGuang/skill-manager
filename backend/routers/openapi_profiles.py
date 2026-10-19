"""Management APIs for Skill scan and Agent evaluation profiles."""
import json
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from agent_manager.api import router as native
from .. import auth, models
from ..api_errors import ApiError
from ..security_scan_controls import AGENT_SCAN_SKILLS
from ..services import openapi_profiles as service
from ..sqlite_db import get_db
from .security_scans import _evaluation_models_query

router = APIRouter(prefix="/external-access/profiles", tags=["external-access"])
Kind = Literal["skill", "agent"]


class ProfileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = Field(min_length=1, max_length=128, strict=True)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    settings: dict

    @field_validator("profile_id")
    @classmethod
    def valid_id(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("Profile ID must not have surrounding whitespace")
        return value


@router.get("/options")
def options(db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return {
        "skills": list(AGENT_SCAN_SKILLS),
        "policies": [{"value": p.policy_id, "label": p.name, "enabled": p.enabled}
                     for p in db.query(models.SecurityScanPolicy).order_by(models.SecurityScanPolicy.name).all()],
        "models": [{"value": m.name, "label": m.display_name or m.name}
                   for m, provider in _evaluation_models_query(db).order_by(models.ModelEndpoint.name).all()],
    }


@router.get("/{kind}")
def list_profiles(kind: Kind, user=Depends(auth.get_current_admin_user), mgr=Depends(native.get_manager)):
    return service.listing(kind, service.config_path(kind, mgr.registry.data_dir))


def validate_references(kind, profile, db):
    ids = profile.platform_ids
    if db.query(models.ExternalPlatform).filter(models.ExternalPlatform.platform_id.in_(ids)).count() != len(ids):
        raise ApiError(422, "openapi_profiles.partner_invalid", "请选择已登记的接入方", "Select registered integration partners")
    if kind == "agent":
        policy = db.query(models.SecurityScanPolicy).filter_by(policy_id=profile.policy_id, enabled=True).first()
        if not policy or policy.execution_mode == "passive" or "conversation" not in json.loads(policy.allowed_capabilities_json):
            raise ApiError(422, "openapi_profiles.policy_invalid", "请选择已启用且允许对话的评测策略", "Select an enabled evaluation policy that permits conversation")
        if profile.conversation_mode == "multi_turn" and "multi_turn" not in json.loads(policy.allowed_capabilities_json):
            raise ApiError(422, "openapi_profiles.policy_invalid", "所选策略需允许多轮对话", "The selected policy must permit multi-turn conversations")
        if not _evaluation_models_query(db).filter(models.ModelEndpoint.name == profile.evaluation_model).first():
            raise ApiError(422, "openapi_profiles.model_invalid", "请选择已启用的评判模型及供应商", "Select an enabled evaluator model and provider")
        if profile.approval_id and not db.query(models.SecurityScanApproval).filter_by(
            approval_id=profile.approval_id, policy_id=profile.policy_id, status="approved").first():
            raise ApiError(422, "openapi_profiles.approval_invalid", "执行审批不存在、已使用或与策略不匹配", "Execution approval is missing, used or does not match the policy")


def write_profile(kind, body, db, mgr, create):
    profile = service.validate_settings(kind, body.settings)
    validate_references(kind, profile, db)
    return service.save(kind, service.config_path(kind, mgr.registry.data_dir), body, create=create)


@router.post("/{kind}", status_code=201)
def create_profile(kind: Kind, body: ProfileWrite, db: Session = Depends(get_db),
                   user=Depends(auth.get_current_admin_user), mgr=Depends(native.get_manager)):
    return write_profile(kind, body, db, mgr, True)


@router.put("/{kind}")
def update_profile(kind: Kind, body: ProfileWrite, db: Session = Depends(get_db),
                   user=Depends(auth.get_current_admin_user), mgr=Depends(native.get_manager)):
    return write_profile(kind, body, db, mgr, False)
