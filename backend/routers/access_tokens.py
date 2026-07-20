import hashlib
import hmac
import ipaddress
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..sqlite_db import get_db


router = APIRouter(prefix="/access/tokens", tags=["access-tokens"])

SCANNER_SCOPES = ["scanner:submit", "scanner:read-own-results", "scanner:read-own-sessions"]
RUNTIME_SCOPES = ["runtime:verify-signature", "runtime:can-load", "runtime:check-tool"]
MODEL_SCOPES = ["model:chat"]
CLIENT_SCOPES = [
    "client:register",
    "client:heartbeat",
    "client:read-policy",
    "client:read-tasks",
    "client:report-inventory",
    "client:report-events",
    "client:submit-skill",
    "client:download-approved-skill",
]
ALLOWED_SCOPES = set(SCANNER_SCOPES + RUNTIME_SCOPES + MODEL_SCOPES + CLIENT_SCOPES)
DEFAULT_SCOPES_BY_TYPE = {
    "model_gateway": ["model:chat"],
    "agent_runtime": list(RUNTIME_SCOPES),
    "scanner": list(SCANNER_SCOPES),
    "client": list(CLIENT_SCOPES),
}
ACTIVE_TOKEN_REQUESTS: dict[int, int] = {}


def _json_loads(value: str | None, default):
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return default


def _json_dumps(value) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _new_token() -> str:
    return "amat_" + secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_scopes(token_type: str, scopes: list[str] | None) -> list[str]:
    requested = scopes if scopes else DEFAULT_SCOPES_BY_TYPE.get(token_type, [])
    result: list[str] = []
    for scope in requested:
        value = str(scope).strip()
        if not value:
            continue
        if value not in ALLOWED_SCOPES:
            raise HTTPException(status_code=400, detail=f"不支持的凭证权限: {value}")
        if value not in result:
            result.append(value)
    return result


def _access_token_response(row: models.AccessToken, token: str | None = None) -> schemas.AccessTokenResponse:
    return schemas.AccessTokenResponse(
        id=row.id,
        name=row.name,
        token_type=row.token_type,
        token_prefix=row.token_prefix,
        token=token,
        token_hash=None,
        bound_agent_id=row.bound_agent_id,
        bound_client_id=row.bound_client_id,
        user_id=row.user_id,
        group_id=row.group_id,
        scopes=_json_loads(row.scopes_json, []),
        allowed_models=_json_loads(row.allowed_models_json, []),
        allowed_ips=_json_loads(row.allowed_ips_json, []),
        status=row.status,
        expires_at=row.expires_at,
        max_body_kb=row.max_body_kb,
        max_concurrent_requests=row.max_concurrent_requests,
        max_upload_mb=row.max_upload_mb,
        max_concurrent_jobs=row.max_concurrent_jobs,
        enable_compression=row.enable_compression,
        compression_level=row.compression_level,
        prompt_guard_mode=getattr(row, "prompt_guard_mode", "off"),
        prompt_guard_llm_review=getattr(row, "prompt_guard_llm_review", False),
        created_by=row.created_by,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        revoked_by=row.revoked_by,
    )


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少接入凭证")
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="缺少接入凭证")
    return token


def _ip_allowed(client_ip: str | None, allowed: list[str]) -> bool:
    if not allowed:
        return True
    if not client_ip:
        return False
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for item in allowed:
        raw = str(item).strip()
        if not raw:
            continue
        try:
            if "/" in raw and ip in ipaddress.ip_network(raw, strict=False):
                return True
            if "/" not in raw and ip == ipaddress.ip_address(raw):
                return True
        except ValueError:
            continue
    return False


def resolve_access_token(
    db: Session,
    authorization: str | None,
    *,
    required_scope: str | tuple[str, ...],
    request: Request | None = None,
) -> models.AccessToken:
    plain = _extract_bearer(authorization)
    row = db.query(models.AccessToken).filter(models.AccessToken.token_hash == _hash_token(plain)).first()
    if not row or row.status != "active":
        raise HTTPException(status_code=403, detail="接入凭证无效或已禁用")
    if row.expires_at and row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="接入凭证已过期")
    scopes = _json_loads(row.scopes_json, [])
    required_scopes = (required_scope,) if isinstance(required_scope, str) else required_scope
    if not any(scope in scopes for scope in required_scopes):
        raise HTTPException(status_code=403, detail=f"接入凭证缺少权限: {' 或 '.join(required_scopes)}")
    allowed_ips = _json_loads(row.allowed_ips_json, [])
    client_ip = request.client.host if request and request.client else None
    if not _ip_allowed(client_ip, allowed_ips):
        raise HTTPException(status_code=403, detail="接入凭证不允许当前来源 IP")
    row.last_used_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def resolve_agent_id(query_agent_id: str | None, header_agent_id: str | None) -> str | None:
    query_value = (query_agent_id or "").strip()
    header_value = (header_agent_id or "").strip()
    if query_value and header_value and query_value != header_value:
        raise HTTPException(status_code=400, detail="agent_id 与 X-Agent-ID 不一致")
    return header_value or query_value or None


def ensure_token_agent_allowed(db: Session, token: models.AccessToken, agent_id: str | None) -> models.ManagedAgent:
    if not agent_id:
        raise HTTPException(status_code=400, detail="缺少 agent_id")
    if token.bound_agent_id and token.bound_agent_id != agent_id:
        raise HTTPException(status_code=403, detail="接入凭证绑定的智能体不匹配")
    agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if agent.status != "active":
        raise HTTPException(status_code=403, detail="智能体未启用")
    return agent


def agent_skill_names(agent: models.ManagedAgent) -> list[str]:
    return [str(item) for item in _json_loads(agent.skill_names_json, [])]


def agent_prompt_names(agent: models.ManagedAgent) -> list[str]:
    return [str(item) for item in _json_loads(agent.prompt_names_json, [])]


def ensure_agent_skill_allowed(agent: models.ManagedAgent, skill_name: str, skill_id: str | None = None) -> None:
    allowed = set(agent_skill_names(agent))
    if skill_name not in allowed and (not skill_id or skill_id not in allowed):
        raise HTTPException(status_code=403, detail="智能体未授权使用该 Skill")


def ensure_agent_prompt_allowed(agent: models.ManagedAgent, prompt_name: str) -> None:
    if prompt_name not in agent_prompt_names(agent):
        raise HTTPException(status_code=403, detail="智能体未授权使用该 Prompt")


def acquire_access_token_slot(token: models.AccessToken) -> None:
    active = ACTIVE_TOKEN_REQUESTS.get(token.id, 0)
    if active >= max(1, token.max_concurrent_requests):
        raise HTTPException(status_code=429, detail="接入凭证并发请求数已达上限")
    ACTIVE_TOKEN_REQUESTS[token.id] = active + 1


def release_access_token_slot(token: models.AccessToken) -> None:
    active = ACTIVE_TOKEN_REQUESTS.get(token.id, 0)
    if active <= 1:
        ACTIVE_TOKEN_REQUESTS.pop(token.id, None)
    else:
        ACTIVE_TOKEN_REQUESTS[token.id] = active - 1


def verify_plain_token(row: models.AccessToken, plain: str) -> bool:
    return hmac.compare_digest(row.token_hash, _hash_token(plain))


@router.get("", response_model=schemas.AccessTokenListResponse)
async def list_access_tokens(
    token_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    query = db.query(models.AccessToken)
    if token_type:
        query = query.filter(models.AccessToken.token_type == token_type)
    rows = query.order_by(models.AccessToken.id.desc()).all()
    return schemas.AccessTokenListResponse(items=[_access_token_response(row) for row in rows])


@router.post("", response_model=schemas.AccessTokenCreateResponse)
async def create_access_token(
    body: schemas.AccessTokenCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="凭证名称不能为空")
    if body.bound_agent_id and not db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == body.bound_agent_id).first():
        raise HTTPException(status_code=404, detail="绑定的智能体不存在")
    if body.user_id and not db.query(models.User).filter(models.User.id == body.user_id).first():
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.group_id and not db.query(models.UserGroup).filter(models.UserGroup.id == body.group_id).first():
        raise HTTPException(status_code=404, detail="用户组不存在")
    scopes = _normalize_scopes(body.token_type, body.scopes)
    plain = _new_token()
    row = models.AccessToken(
        name=body.name.strip(),
        token_type=body.token_type,
        token_hash=_hash_token(plain),
        token_prefix=plain[:12],
        scopes_json=_json_dumps(scopes),
        bound_agent_id=body.bound_agent_id,
        bound_client_id=body.bound_client_id,
        user_id=body.user_id or current_user.id if body.token_type == "model_gateway" else body.user_id,
        group_id=body.group_id,
        allowed_models_json=_json_dumps(body.allowed_models),
        allowed_ips_json=_json_dumps(body.allowed_ips),
        expires_at=body.expires_at,
        max_body_kb=body.max_body_kb,
        max_concurrent_requests=body.max_concurrent_requests,
        max_upload_mb=body.max_upload_mb,
        max_concurrent_jobs=body.max_concurrent_jobs,
        enable_compression=body.enable_compression,
        compression_level=body.compression_level,
        prompt_guard_mode=body.prompt_guard_mode,
        prompt_guard_llm_review=body.prompt_guard_llm_review,
        created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return schemas.AccessTokenCreateResponse(token=plain, record=_access_token_response(row))


@router.put("/{token_id}", response_model=schemas.AccessTokenResponse)
async def update_access_token(
    token_id: int,
    body: schemas.AccessTokenUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.AccessToken).filter(models.AccessToken.id == token_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="接入凭证不存在")
    data = body.model_dump(exclude_unset=True)
    if "scopes" in data and data["scopes"] is not None:
        row.scopes_json = _json_dumps(_normalize_scopes(row.token_type, data.pop("scopes")))
    if "allowed_models" in data and data["allowed_models"] is not None:
        row.allowed_models_json = _json_dumps(data.pop("allowed_models"))
    if "allowed_ips" in data and data["allowed_ips"] is not None:
        row.allowed_ips_json = _json_dumps(data.pop("allowed_ips"))
    if "bound_agent_id" in data and data["bound_agent_id"]:
        if not db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == data["bound_agent_id"]).first():
            raise HTTPException(status_code=404, detail="绑定的智能体不存在")
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _access_token_response(row)


@router.post("/{token_id}/revoke", response_model=schemas.AccessTokenResponse)
async def revoke_access_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.AccessToken).filter(models.AccessToken.id == token_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="接入凭证不存在")
    row.status = "revoked"
    row.revoked_at = datetime.utcnow()
    row.revoked_by = current_user.username
    db.commit()
    db.refresh(row)
    return _access_token_response(row)


@router.delete("/{token_id}")
async def delete_access_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.AccessToken).filter(models.AccessToken.id == token_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="接入凭证不存在")
    db.delete(row)
    db.commit()
    return {"status": "deleted"}
