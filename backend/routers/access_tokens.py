import hashlib
import hmac
import ipaddress
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, object_session

from .. import auth, models, schemas
from ..api_errors import ApiError
from ..sqlite_db import get_db
from ..request_leases import LeaseLimitExceeded, acquire_lease, release_lease
from ..agent_mcp import ensure_agent_mcp_scope
from ..external_access import OPENAPI_SCOPES, validate_binding

router = APIRouter(prefix="/access/tokens", tags=["access-tokens"])

SCANNER_SCOPES = ["scanner:submit", "scanner:read-own-results", "scanner:read-own-sessions"]
RUNTIME_SCOPES = [
    "runtime:verify-signature",
    "runtime:can-load",
    "runtime:check-tool",
    "runtime:govern",
    "runtime:memory",
    "runtime:trace",
]
AGENT_VERIFICATION_SCOPES = [
    "runtime:verify-signature",
    "runtime:can-load",
    "runtime:check-tool",
    "runtime:trace",
]
MODEL_SCOPES = ["model:chat"]
MCP_SCOPES = ["mcp:connect", "mcp:list-tools", "mcp:call-tools"]
CLIENT_SCOPES = [
    "client:register",
    "client:heartbeat",
    "client:read-policy",
    "client:read-tasks",
    "client:report-inventory",
    "client:report-events",
    "client:submit-skill",
    "client:download-approved-skill",
    "client:request-skill-actions",
]
AIDR_SCOPES = ["aidr:heartbeat", "aidr:report-events"]
ALLOWED_SCOPES = set(SCANNER_SCOPES + RUNTIME_SCOPES + MODEL_SCOPES + MCP_SCOPES + CLIENT_SCOPES + AIDR_SCOPES + OPENAPI_SCOPES)
DEFAULT_SCOPES_BY_TYPE = {
    "model_gateway": ["model:chat"],
    "agent_runtime": list(AGENT_VERIFICATION_SCOPES),
    "scanner": list(SCANNER_SCOPES),
    "client": list(CLIENT_SCOPES),
    "mcp_gateway": list(MCP_SCOPES),
}
LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)

SCOPE_TOKEN_TYPES = {
    **{scope: {"openapi"} for scope in OPENAPI_SCOPES},
    **{scope: {"scanner"} for scope in SCANNER_SCOPES},
    **{scope: {"agent_runtime"} for scope in RUNTIME_SCOPES},
    "model:chat": {"model_gateway", "agent_runtime"},
    **{scope: {"mcp_gateway", "agent_runtime"} for scope in MCP_SCOPES},
    **{scope: {"client"} for scope in CLIENT_SCOPES},
    **{scope: {"client"} for scope in AIDR_SCOPES},
}


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


def _validate_allowed_ips(values: list[str]) -> None:
    """在写入前校验来源地址，错误仅返回位置以供界面定位草稿。"""
    invalid: list[int] = []
    for index, value in enumerate(values, start=1):
        raw = value.strip()
        address, separator, prefix = raw.partition("/")
        try:
            numeric_prefix = prefix.isascii() and prefix.isdecimal()
            if "%" in address or (separator and not numeric_prefix):
                raise ValueError
            ipaddress.ip_address(address)
            if separator:
                ipaddress.ip_network(raw, strict=False)
        except ValueError:
            invalid.append(index)
    if invalid:
        raise ApiError(
            400,
            "credential.invalid_allowed_ips",
            "请检查允许来源 IP / CIDR 的格式",
            "Check the allowed source IP / CIDR format",
            params={"indices": invalid},
        )


def _normalize_scopes(token_type: str, scopes: list[str] | None) -> list[str]:
    if token_type == "openapi" and not scopes:
        raise ApiError(400, "external_access.scopes_required", "请选择至少一项接口权限", "Select at least one API permission")
    requested = scopes if scopes else DEFAULT_SCOPES_BY_TYPE.get(token_type, [])
    result: list[str] = []
    for scope in requested:
        value = str(scope).strip()
        if not value:
            continue
        if value not in ALLOWED_SCOPES:
            raise ApiError(
                400,
                "credential.unsupported_scope",
                f"不支持的凭证权限: {value}",
                f"Unsupported credential scope: {value}",
                params={"scope": value},
            )
        if token_type not in SCOPE_TOKEN_TYPES[value]:
            raise ApiError(
                400,
                "credential.scope_type_mismatch",
                f"凭证类型 {token_type} 不支持权限: {value}",
                f"Credential type {token_type} does not support scope: {value}",
                params={"token_type": token_type, "scope": value},
            )
        if value not in result:
            result.append(value)
    if token_type == "openapi" and not result:
        raise ApiError(400, "external_access.scopes_required", "请选择至少一项接口权限", "Select at least one API permission")
    return result


def _validate_external_token(db, token_type, platform_id, department_ids, expires_at, *, require_enabled=True):
    if token_type != "openapi":
        if platform_id or department_ids:
            raise ApiError(400, "external_access.token_type_invalid", "接入方授权需要使用外部接口凭证", "Partner authorization requires an external API credential")
        return expires_at
    validate_binding(db, platform_id, department_ids, require_enabled=require_enabled)
    if expires_at and expires_at.tzinfo:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if expires_at and expires_at <= datetime.utcnow():
        raise ApiError(400, "external_access.expiry_invalid", "到期时间须晚于当前时间", "Expiry must be in the future")
    return expires_at


def _validate_manual_credential_export(token_type, issuance, export):
    if export and (token_type != "client" or not issuance):
        raise ApiError(400, "credential.manual_export_not_allowed", "手动领取权限需要客户端凭证同时允许创建 Agent 运行凭证", "Manual credential export requires a Client credential with Agent credential issuance enabled")


def _normalize_allowed_models(
    token_type: str,
    scopes: list[str],
    allowed_models: list[str] | None,
    allow_agent_credential_issuance: bool = False,
    db: Session | None = None,
) -> list[str]:
    result: list[str] = []
    for model in allowed_models or []:
        value = str(model).strip()
        if value and value not in result:
            result.append(value)
    direct_model_access = token_type in {"model_gateway", "agent_runtime"} and "model:chat" in scopes
    delegated_model_access = token_type == "client" and allow_agent_credential_issuance
    if result and not (direct_model_access or delegated_model_access):
        raise ApiError(
            400,
            "credential.models_not_applicable",
            "当前凭证类型或权限不支持配置允许的模型",
            "Allowed models are not applicable to this credential type or scope",
            params={"token_type": token_type},
        )
    if db is not None and result:
        selected = db.query(models.ModelEndpoint).filter(models.ModelEndpoint.name.in_(result)).all()
        upstream_names: set[str] = set()
        for model in selected:
            upstream = model.upstream_name or model.name
            if upstream in upstream_names:
                raise ApiError(422, "credential.duplicate_upstream_model", "同名上游模型只能选择一个供应商", "Select only one provider for each upstream model name")
            upstream_names.add(upstream)
    return result


def _validate_agent_credential_issuance(token_type: str, allowed: bool) -> None:
    if allowed and token_type != "client":
        raise ApiError(
            400,
            "credential.agent_issuance_not_applicable",
            "只有客户端接入凭证可以代客户端为绑定 Agent 创建运行凭证",
            "Only Client access credentials may create runtime credentials for local Agents",
            params={"token_type": token_type},
        )


def _validate_subject_bindings(
    db: Session,
    *,
    token_type: str,
    bound_agent_id: str | None,
    bound_client_id: str | None,
    allowed_mcp_gateways: list[str] | None,
    scopes: list[str] | None = None,
) -> list[str]:
    if token_type == "agent_runtime":
        if not bound_agent_id:
            raise ApiError(
                400,
                "credential.agent_binding_required",
                "Agent 运行凭证必须绑定智能体",
                "Agent runtime credentials must be bound to an Agent",
            )
        if not db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == bound_agent_id).first():
            raise ApiError(404, "agent.bound_not_found", "绑定的智能体不存在", "The bound Agent does not exist")
    elif bound_agent_id:
        raise ApiError(
            400,
            "credential.agent_binding_not_applicable",
            "当前凭证类型不能绑定智能体",
            "This credential type cannot be bound to an Agent",
            params={"token_type": token_type},
        )

    if token_type != "client" and bound_client_id:
        raise ApiError(
            400,
            "credential.client_binding_not_applicable",
            "当前凭证类型不能绑定客户端",
            "This credential type cannot be bound to a client",
            params={"token_type": token_type},
        )

    gateways = [str(item).strip() for item in (allowed_mcp_gateways or []) if str(item).strip()]
    uses_mcp = token_type == "mcp_gateway" or any(scope in MCP_SCOPES for scope in (scopes or []))
    if token_type == "agent_runtime" and not uses_mcp:
        return []
    if token_type in {"mcp_gateway", "agent_runtime"}:
        if not gateways:
            if uses_mcp:
                raise ApiError(
                    400,
                    "credential.mcp_gateway_binding_required",
                    "使用 MCP 权限的凭证必须至少授权一个网关",
                    "Credentials with MCP scopes must allow at least one gateway",
                )
            return []
        existing = {row.slug for row in db.query(models.McpGateway).all()}
        missing = set(gateways) - existing
        if missing:
            names = ", ".join(sorted(missing))
            raise ApiError(
                404,
                "mcp.gateway_not_found",
                f"MCP 网关不存在: {names}",
                f"MCP gateway not found: {names}",
                params={"gateways": sorted(missing)},
            )
    elif gateways:
        raise ApiError(
            400,
            "credential.mcp_gateway_binding_not_applicable",
            "当前凭证类型不能配置 MCP 网关范围",
            "This credential type cannot configure MCP gateway access",
            params={"token_type": token_type},
        )
    if token_type == "agent_runtime" and uses_mcp:
        ensure_agent_mcp_scope(db, models.AccessToken(token_type=token_type, bound_agent_id=bound_agent_id), gateways)
    return list(dict.fromkeys(gateways))


def _access_token_response(row: models.AccessToken, token: str | None = None) -> schemas.AccessTokenResponse:
    return schemas.AccessTokenResponse(
        privacy_policy_id=row.privacy_policy_id,
        platform_id=row.platform_id,
        allowed_department_ids=_json_loads(row.allowed_department_ids_json, []),
        id=row.id,
        name=row.name,
        token_type=row.token_type,
        token_prefix=row.token_prefix,
        token=token,
        token_hash=None,
        bound_agent_id=row.bound_agent_id,
        bound_client_id=row.bound_client_id,
        allow_agent_credential_issuance=getattr(row, "allow_agent_credential_issuance", False),
        allow_manual_credential_export=row.allow_manual_credential_export,
        issued_by_client_token_id=getattr(row, "issued_by_client_token_id", None),
        user_id=row.user_id,
        group_id=row.group_id,
        scopes=_json_loads(row.scopes_json, []),
        allowed_models=_json_loads(row.allowed_models_json, []),
        allowed_mcp_gateways=_json_loads(row.allowed_mcp_gateways_json, []),
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
        raise ApiError(401, "credential.missing", "缺少接入凭证", "Missing access credential")
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise ApiError(401, "credential.missing", "缺少接入凭证", "Missing access credential")
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
    allowed_token_types: set[str] | None = None,
) -> models.AccessToken:
    plain = _extract_bearer(authorization)
    row = db.query(models.AccessToken).filter(models.AccessToken.token_hash == _hash_token(plain)).first()
    if not row or row.status != "active":
        raise ApiError(
            403,
            "credential.invalid_or_disabled",
            "接入凭证无效或已禁用",
            "The access credential is invalid or disabled",
        )
    if row.expires_at and row.expires_at < datetime.utcnow():
        raise ApiError(403, "credential.expired", "接入凭证已过期", "The access credential has expired")
    scopes = _json_loads(row.scopes_json, [])
    required_scopes = (required_scope,) if isinstance(required_scope, str) else required_scope
    if not any(scope in scopes for scope in required_scopes):
        scope_text_zh = " 或 ".join(required_scopes)
        scope_text_en = " or ".join(required_scopes)
        raise ApiError(
            403,
            "credential.scope_missing",
            f"接入凭证缺少权限: {scope_text_zh}",
            f"The access credential requires scope: {scope_text_en}",
            params={"scopes": list(required_scopes)},
        )
    expected_types = allowed_token_types or {
        token_type
        for scope in required_scopes
        for token_type in SCOPE_TOKEN_TYPES.get(scope, set())
    }
    if expected_types and row.token_type not in expected_types:
        raise ApiError(
            403,
            "credential.type_mismatch",
            "接入凭证类型不允许访问当前接口",
            "The credential type is not allowed for this endpoint",
            params={"allowed_token_types": sorted(expected_types), "token_type": row.token_type},
        )
    if row.token_type == "agent_runtime" and not (row.bound_agent_id or "").strip():
        raise ApiError(
            403,
            "credential.agent_binding_required",
            "Agent 运行凭证未绑定智能体，请重新签发或绑定后再使用",
            "The Agent runtime credential is not bound to an Agent; reissue or bind it before use",
        )
    allowed_ips = _json_loads(row.allowed_ips_json, [])
    client_ip = request.client.host if request and request.client else None
    if not _ip_allowed(client_ip, allowed_ips):
        raise ApiError(
            403,
            "credential.ip_not_allowed",
            "接入凭证不允许当前来源 IP",
            "The source IP is not allowed by this credential",
        )
    return _touch_last_used(db, row)


def _touch_last_used(db: Session, row: models.AccessToken) -> models.AccessToken:
    now = datetime.utcnow()
    if row.last_used_at and now - row.last_used_at < LAST_USED_WRITE_INTERVAL:
        return row
    row.last_used_at = now
    try:
        db.commit()
        db.refresh(row)
    except OperationalError as exc:
        db.rollback()
        if "database is locked" not in str(exc).lower():
            raise
    return row


def resolve_agent_id(query_agent_id: str | None, header_agent_id: str | None) -> str | None:
    query_value = (query_agent_id or "").strip()
    header_value = (header_agent_id or "").strip()
    if query_value and header_value and query_value != header_value:
        raise ApiError(
            400,
            "agent.id_mismatch",
            "agent_id 与 X-Agent-ID 不一致",
            "agent_id does not match X-Agent-ID",
        )
    return header_value or query_value or None


def ensure_token_agent_allowed(db: Session, token: models.AccessToken, agent_id: str | None) -> models.ManagedAgent:
    if not agent_id:
        raise ApiError(400, "agent.id_missing", "缺少 agent_id", "Missing agent_id")
    if token.bound_agent_id and token.bound_agent_id != agent_id:
        raise ApiError(
            403,
            "agent.credential_binding_mismatch",
            "接入凭证绑定的智能体不匹配",
            "The credential is bound to a different Agent",
        )
    agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == agent_id).first()
    if not agent:
        raise ApiError(404, "agent.not_found", "智能体不存在", "Agent not found")
    if agent.status != "active":
        raise ApiError(403, "agent.disabled", "智能体未启用", "Agent is disabled")
    return agent


def agent_skill_names(agent: models.ManagedAgent) -> list[str]:
    return [str(item) for item in _json_loads(agent.skill_names_json, [])]


def agent_prompt_names(agent: models.ManagedAgent) -> list[str]:
    return [str(item) for item in _json_loads(agent.prompt_names_json, [])]


def ensure_agent_skill_allowed(
    agent: models.ManagedAgent,
    skill_name: str,
    skill_id: str | None = None,
    family_id: str | None = None,
) -> None:
    allowed = set(agent_skill_names(agent))
    accepted_refs = {ref for ref in (skill_name, skill_id, family_id) if ref}
    if allowed.isdisjoint(accepted_refs):
        raise ApiError(
            403,
            "agent.skill_not_allowed",
            "智能体未授权使用该 Skill",
            "The Agent is not authorized to use this Skill",
            params={"skill_name": skill_name, "skill_id": skill_id, "family_id": family_id},
        )


def ensure_agent_prompt_allowed(agent: models.ManagedAgent, prompt_name: str) -> None:
    if prompt_name not in agent_prompt_names(agent):
        raise ApiError(
            403,
            "agent.prompt_not_allowed",
            "智能体未授权使用该 Prompt",
            "The Agent is not authorized to use this Prompt",
            params={"prompt_name": prompt_name},
        )


def acquire_access_token_slot(token: models.AccessToken, *, bind=None) -> None:
    session = object_session(token)
    bind = bind or (session.get_bind() if session is not None else None)
    try:
        lease_id = acquire_lease(
            "access_token",
            token.id,
            "request",
            token.max_concurrent_requests,
            **({"bind": bind} if bind is not None else {}),
        )
    except LeaseLimitExceeded:
        raise ApiError(
            429,
            "credential.concurrency_limit",
            "接入凭证并发请求数已达上限",
            "The credential concurrency limit has been reached",
        )
    leases = getattr(token, "_request_lease_ids", None)
    if leases is None:
        leases = []
        setattr(token, "_request_lease_ids", leases)
    leases.append((lease_id, bind))


def release_access_token_slot(token: models.AccessToken) -> None:
    leases = getattr(token, "_request_lease_ids", None) or []
    lease = leases.pop() if leases else None
    if lease:
        lease_id, bind = lease
        release_lease(lease_id, **({"bind": bind} if bind is not None else {}))


def verify_plain_token(row: models.AccessToken, plain: str) -> bool:
    return hmac.compare_digest(row.token_hash, _hash_token(plain))


@router.get("", response_model=schemas.AccessTokenListResponse)
async def list_access_tokens(
    token_type: str | None = None,
    token_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    query = db.query(models.AccessToken)
    if token_id is not None:
        query = query.filter(models.AccessToken.id == token_id)
    if token_type:
        query = query.filter(models.AccessToken.token_type == token_type)
    rows = query.order_by(models.AccessToken.id.desc()).all()
    return schemas.AccessTokenListResponse(items=[_access_token_response(row) for row in rows])


def _validate_privacy_policy(db, policy_id, token_type, scopes, agent_issuance):
    if policy_id is None:
        return
    if "model:chat" not in scopes and not (token_type == "client" and agent_issuance):
        raise ApiError(400, "privacy.model_access_required", "仅模型调用或代发模型凭证可指定隐私策略", "Privacy policies require model access or delegated model credentials")
    if db.get(models.PrivacyPolicy, policy_id) is None:
        raise ApiError(404, "privacy.policy_not_found", "隐私策略不存在", "Privacy policy not found")


@router.get("/privacy-policies")
async def credential_privacy_policies(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_active_user),
):
    from .. import iam
    if not iam.permission_codes(db, current_user) & {"credentials:view", "credentials:create", "credentials:update"}:
        iam.check(db, current_user, "credentials:view")
    from .llm_gateway import _get_default_policy
    default = _get_default_policy(db)
    return [{"id": row.id, "name": row.name, "is_default": row.id == default.id}
            for row in db.query(models.PrivacyPolicy).order_by(models.PrivacyPolicy.id).all()]


@router.post("", response_model=schemas.AccessTokenCreateResponse)
async def create_access_token(
    body: schemas.AccessTokenCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    _validate_allowed_ips(body.allowed_ips)
    if not body.name.strip():
        raise ApiError(400, "credential.name_required", "凭证名称不能为空", "Credential name is required")
    expiry = _validate_external_token(db, body.token_type, body.platform_id, body.allowed_department_ids, body.expires_at)
    if body.token_type == "openapi" and len(body.name.strip()) > 128:
        raise ApiError(400, "external_access.name_too_long", "凭证名称最多128个字符", "Credential names allow up to 128 characters")
    _validate_agent_credential_issuance(body.token_type, body.allow_agent_credential_issuance)
    _validate_manual_credential_export(body.token_type, body.allow_agent_credential_issuance, body.allow_manual_credential_export)
    scopes = _normalize_scopes(body.token_type, body.scopes)
    _validate_privacy_policy(db, body.privacy_policy_id, body.token_type, scopes, body.allow_agent_credential_issuance)
    allowed_mcp_gateways = _validate_subject_bindings(
        db,
        token_type=body.token_type,
        bound_agent_id=body.bound_agent_id,
        bound_client_id=body.bound_client_id,
        allowed_mcp_gateways=body.allowed_mcp_gateways,
        scopes=scopes,
    )
    if body.user_id and not db.query(models.User).filter(models.User.id == body.user_id).first():
        raise ApiError(404, "user.not_found", "用户不存在", "User not found")
    if body.group_id and not db.query(models.UserGroup).filter(models.UserGroup.id == body.group_id).first():
        raise ApiError(404, "group.not_found", "用户组不存在", "User group not found")
    plain = _new_token()
    row = models.AccessToken(
        privacy_policy_id=body.privacy_policy_id,
        platform_id=body.platform_id,
        allowed_department_ids_json=_json_dumps(list(dict.fromkeys(body.allowed_department_ids))),
        name=body.name.strip(),
        token_type=body.token_type,
        token_hash=_hash_token(plain),
        token_prefix=plain[:12],
        scopes_json=_json_dumps(scopes),
        bound_agent_id=body.bound_agent_id,
        bound_client_id=body.bound_client_id,
        allow_agent_credential_issuance=body.allow_agent_credential_issuance,
        allow_manual_credential_export=body.allow_manual_credential_export,
        user_id=body.user_id or current_user.id if body.token_type == "model_gateway" else body.user_id,
        group_id=body.group_id,
        allowed_models_json=_json_dumps(
            _normalize_allowed_models(
                body.token_type,
                scopes,
                body.allowed_models,
                body.allow_agent_credential_issuance,
                db=db,
            )
        ),
        allowed_mcp_gateways_json=_json_dumps(allowed_mcp_gateways),
        allowed_ips_json=_json_dumps(body.allowed_ips),
        expires_at=expiry,
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
        raise ApiError(404, "credential.not_found", "接入凭证不存在", "Access credential not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("allowed_ips") is not None:
        _validate_allowed_ips(data["allowed_ips"])
    if row.status == "revoked" and row.token_type != "openapi":
        raise ApiError(409, "credential.revoked", "凭证已吊销，请创建新凭证", "This credential is revoked; create a new one")
    if row.token_type != "openapi" and "scopes" in data and not any(scope.strip() for scope in (data["scopes"] or [])):
        raise ApiError(400, "credential.scopes_required", "请至少保留一项权限；停止使用请吊销凭证", "Keep at least one permission; revoke the credential to stop using it")
    if "allow_manual_credential_export" in data and data["allow_manual_credential_export"] is None:
        raise ApiError(400, "credential.manual_export_required", "手动领取权限必须为开启或关闭", "Manual retrieval permission must be enabled or disabled")
    if row.token_type == "openapi":
        for field in ("status", "name", "scopes", "allowed_department_ids"):
            if field in data and data[field] is None:
                raise ApiError(400, "external_access.field_required", "提交的字段不能为空", "Submitted fields must not be null")
        if row.status == "revoked":
            raise ApiError(409, "external_access.token_revoked", "凭证已吊销，请创建新凭证", "This credential is revoked; create a new one")
        if "name" in data and (not data["name"] or not data["name"].strip()):
            raise ApiError(400, "credential.name_required", "凭证名称不能为空", "Credential name is required")
        if "name" in data:
            data["name"] = data["name"].strip()
            if len(data["name"]) > 128:
                raise ApiError(400, "external_access.name_too_long", "凭证名称最多128个字符", "Credential names allow up to 128 characters")
        if data.get("status") == "revoked":
            row.revoked_at = datetime.utcnow()
            row.revoked_by = current_user.username
        if "scopes" in data:
            _normalize_scopes("openapi", data["scopes"])
        if "allowed_department_ids" in data:
            validate_binding(db, row.platform_id, data["allowed_department_ids"])
        if "expires_at" in data:
            data["expires_at"] = _validate_external_token(db, row.token_type, row.platform_id,
                data.get("allowed_department_ids", _json_loads(row.allowed_department_ids_json, [])), data["expires_at"], require_enabled=False)
    elif data.get("allowed_department_ids"):
        raise ApiError(400, "external_access.token_type_invalid", "接入方授权需要使用外部接口凭证", "Partner authorization requires an external API credential")
    if "allowed_department_ids" in data:
        row.allowed_department_ids_json = _json_dumps(list(dict.fromkeys(data.pop("allowed_department_ids") or [])))
    if "allow_agent_credential_issuance" in data:
        _validate_agent_credential_issuance(row.token_type, bool(data["allow_agent_credential_issuance"]))
    next_bound_agent_id = data.get("bound_agent_id", row.bound_agent_id)
    next_bound_client_id = data.get("bound_client_id", row.bound_client_id)
    next_allowed_mcp_gateways = data.get(
        "allowed_mcp_gateways",
        _json_loads(row.allowed_mcp_gateways_json, []),
    )
    next_scopes = (
        _normalize_scopes(row.token_type, data["scopes"])
        if "scopes" in data and data["scopes"] is not None
        else _json_loads(row.scopes_json, [])
    )
    authorization_changed = (
        bool({"bound_agent_id", "bound_client_id", "allowed_mcp_gateways", "scopes"}.intersection(data))
        or data.get("status") == "active"
    )
    normalized_mcp_gateways = _validate_subject_bindings(
        db,
        token_type=row.token_type,
        bound_agent_id=next_bound_agent_id,
        bound_client_id=next_bound_client_id,
        allowed_mcp_gateways=next_allowed_mcp_gateways,
        scopes=next_scopes,
    ) if authorization_changed else next_allowed_mcp_gateways
    scopes = next_scopes
    next_agent_issuance = bool(data.get("allow_agent_credential_issuance", row.allow_agent_credential_issuance))
    policy_id = data.get("privacy_policy_id", row.privacy_policy_id)
    if "model:chat" not in scopes and not (row.token_type == "client" and next_agent_issuance) and "privacy_policy_id" not in data:
        data["privacy_policy_id"] = policy_id = None
    _validate_privacy_policy(db, policy_id, row.token_type, scopes, next_agent_issuance)
    if not next_agent_issuance and "allow_manual_credential_export" not in data:
        data["allow_manual_credential_export"] = False
    _validate_manual_credential_export(row.token_type, next_agent_issuance, data.get("allow_manual_credential_export", row.allow_manual_credential_export))
    if "scopes" in data and data["scopes"] is not None:
        data.pop("scopes")
        row.scopes_json = _json_dumps(scopes)
        if "model:chat" not in scopes and not (row.token_type == "client" and next_agent_issuance):
            row.allowed_models_json = "[]"
    if "allowed_models" in data and data["allowed_models"] is not None:
        row.allowed_models_json = _json_dumps(
            _normalize_allowed_models(
                row.token_type,
                scopes,
                data.pop("allowed_models"),
                next_agent_issuance,
                db=db,
            )
        )
    if row.token_type == "client" and not next_agent_issuance:
        row.allowed_models_json = "[]"
    if "allowed_mcp_gateways" in data and data["allowed_mcp_gateways"] is not None:
        data.pop("allowed_mcp_gateways")
    if row.token_type in {"mcp_gateway", "agent_runtime"}:
        row.allowed_mcp_gateways_json = _json_dumps(normalized_mcp_gateways)
    if "allowed_ips" in data and data["allowed_ips"] is not None:
        row.allowed_ips_json = _json_dumps(data.pop("allowed_ips"))
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
        raise ApiError(404, "credential.not_found", "接入凭证不存在", "Access credential not found")
    row.status = "revoked"
    row.revoked_at = datetime.utcnow()
    row.revoked_by = current_user.username
    if row.token_type == "client":
        db.query(models.AccessToken).filter(
            models.AccessToken.issued_by_client_token_id == row.id,
            models.AccessToken.status == "active",
        ).update(
            {
                "status": "revoked",
                "revoked_at": row.revoked_at,
                "revoked_by": current_user.username,
            },
            synchronize_session=False,
        )
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
        raise ApiError(404, "credential.not_found", "接入凭证不存在", "Access credential not found")
    if row.token_type == "client":
        now = datetime.utcnow()
        db.query(models.AccessToken).filter(
            models.AccessToken.issued_by_client_token_id == row.id,
            models.AccessToken.status == "active",
        ).update(
            {"status": "revoked", "revoked_at": now, "revoked_by": current_user.username},
            synchronize_session=False,
        )
    db.delete(row)
    db.commit()
    return {"status": "deleted"}
