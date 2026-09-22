import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..api_errors import ApiError
from ..sqlite_db import get_db
from ..external_ai_gateway import binding_models, delete_binding_remote, ensure_binding
from .clients import _client_managed_agent_id


router = APIRouter(prefix="/agents", tags=["agents"])
_CLIENT_ONLINE_WINDOW = timedelta(minutes=10)


def _json_list(value: str | None) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _dump_list(values: list[str] | None) -> str:
    return json.dumps([item.strip() for item in (values or []) if item.strip()], ensure_ascii=False)


def _department_name(db: Session, group_id: int | None) -> str | None:
    if group_id is None:
        return None
    group = db.query(models.UserGroup).filter(models.UserGroup.id == group_id).first()
    return group.name if group else None


def _agent_response(db: Session, row: models.ManagedAgent) -> schemas.ManagedAgentResponse:
    runtime_token = (
        db.query(models.AccessToken)
        .filter(
            models.AccessToken.token_type == "agent_runtime",
            models.AccessToken.bound_agent_id == row.agent_id,
        )
        .order_by(models.AccessToken.id.desc())
        .first()
    )
    gateway = db.get(models.ExternalAIGateway, row.external_gateway_id) if row.external_gateway_id else None
    return schemas.ManagedAgentResponse(
        id=row.id,
        agent_id=row.agent_id,
        name=row.name,
        department_group_id=row.department_group_id,
        department_name=_department_name(db, row.department_group_id),
        owner=row.owner,
        description=row.description,
        channel=row.channel,
        status=row.status,
        default_model=row.default_model,
        default_model_source=row.default_model_source or "internal",
        external_gateway_id=row.external_gateway_id,
        external_gateway_name=gateway.name if gateway else None,
        origin_type=row.origin_type or "platform",
        skill_names=_json_list(row.skill_names_json),
        prompt_names=_json_list(row.prompt_names_json),
        runtime_token_id=runtime_token.id if runtime_token else None,
        runtime_token_name=runtime_token.name if runtime_token else None,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _ensure_department(db: Session, group_id: int | None) -> None:
    if group_id is None:
        return
    if not db.query(models.UserGroup).filter(models.UserGroup.id == group_id).first():
        raise HTTPException(status_code=404, detail="部门不存在")


def _owned_agents(db: Session, current_user: models.User):
    query = db.query(models.ManagedAgent)
    if current_user.role != "super_admin":
        query = query.filter(models.ManagedAgent.created_by == current_user.username)
    return query


def _visible_clients(db: Session, current_user: models.User):
    query = db.query(models.ManagedClient)
    if current_user.role != "super_admin":
        query = query.filter(models.ManagedClient.registered_by == current_user.username)
    return query


def _load_dict(value: str | None) -> dict:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _client_online(client: models.ManagedClient) -> bool:
    return bool(client.last_seen_at and datetime.utcnow() - client.last_seen_at <= _CLIENT_ONLINE_WINDOW)


def _local_agent_id(row: models.ClientAgent) -> str:
    return (row.local_agent_id or row.agent_type).strip() or row.agent_type


def _normalized_gateway_url(value: object) -> str:
    normalized = str(value or "").strip().rstrip("/").lower()
    return normalized[:-3] if normalized.endswith("/v1") else normalized


def _reported_external_gateway(
    managed_agent_id: str,
    instances: list[schemas.AgentAssetInstance],
    bindings_by_agent: dict[str, list[models.ExternalGatewayAgentBinding]],
    gateways_by_id: dict[int, models.ExternalAIGateway],
) -> models.ExternalAIGateway | None:
    bindings = bindings_by_agent.get(managed_agent_id, [])
    bound_gateway_ids = {binding.gateway_id for binding in bindings}
    for instance in instances:
        state = instance.capabilities.get("model_config_state") or {}
        if not isinstance(state, dict):
            continue
        source = str(state.get("gateway_source") or "").strip().lower()
        credential_source = str(state.get("credential_source") or "").strip().lower()
        if source not in {"external", "external_gateway"} and credential_source != "external_gateway":
            continue

        reported_id = state.get("gateway_id")
        try:
            gateway_id = int(reported_id) if reported_id is not None else None
        except (TypeError, ValueError):
            gateway_id = None
        if gateway_id in bound_gateway_ids and gateway_id in gateways_by_id:
            return gateways_by_id[gateway_id]

        reported_url = _normalized_gateway_url(state.get("gateway_url"))
        if reported_url:
            for binding in bindings:
                gateway = gateways_by_id.get(binding.gateway_id)
                if gateway and _normalized_gateway_url(gateway.model_base_url) == reported_url:
                    return gateway
    return None


def _asset_instance(
    client: models.ManagedClient,
    agent: models.ClientAgent,
    skills: list[models.ClientSkillInstall],
) -> schemas.AgentAssetInstance:
    return schemas.AgentAssetInstance(
        client_id=client.client_id,
        client_name=client.name,
        hostname=client.hostname,
        os=client.os,
        arch=client.arch,
        client_version=client.client_version,
        client_status="online" if _client_online(client) else "offline",
        client_last_seen_at=client.last_seen_at,
        local_agent_id=_local_agent_id(agent),
        agent_type=agent.agent_type,
        agent_version=agent.agent_version,
        install_path=agent.install_path,
        skills_path=agent.skills_path,
        skill_management_supported=agent.skill_management_supported,
        capabilities=_load_dict(agent.capabilities_json),
        desired_model=agent.desired_model,
        applied_model=agent.applied_model,
        model_config_status=agent.model_config_status,
        model_config_error=agent.model_config_error,
        last_scanned_at=agent.last_scanned_at,
        skills=[
            schemas.AgentAssetSkill(
                name=skill.skill_name,
                path=skill.skill_path,
                status=skill.status,
                signature=skill.signature,
                version_no=skill.version_no,
                verified_at=skill.verified_at,
            )
            for skill in skills
        ],
    )


def _asset_rows(db: Session, current_user: models.User) -> list[schemas.AgentAssetResponse]:
    managed_agents = _owned_agents(db, current_user).order_by(models.ManagedAgent.id.asc()).all()
    clients = _visible_clients(db, current_user).order_by(models.ManagedClient.id.asc()).all()
    clients_by_id = {client.client_id: client for client in clients}
    client_ids = list(clients_by_id)
    local_agents = (
        db.query(models.ClientAgent)
        .filter(models.ClientAgent.client_id.in_(client_ids))
        .order_by(models.ClientAgent.id.asc())
        .all()
        if client_ids
        else []
    )
    installs = (
        db.query(models.ClientSkillInstall)
        .filter(models.ClientSkillInstall.client_id.in_(client_ids))
        .order_by(models.ClientSkillInstall.id.asc())
        .all()
        if client_ids
        else []
    )
    skills_by_agent: dict[tuple[str, str], list[models.ClientSkillInstall]] = {}
    for skill in installs:
        skills_by_agent.setdefault((skill.client_id, skill.agent_type), []).append(skill)
    bindings: dict[str, list[models.ClientAgent]] = {}
    discovery_bindings: dict[str, list[models.ClientAgent]] = {}
    for local in local_agents:
        if local.managed_agent_id:
            bindings.setdefault(local.managed_agent_id, []).append(local)
        discovery_id = _client_managed_agent_id(local.client_id, _local_agent_id(local))
        discovery_bindings.setdefault(discovery_id, []).append(local)

    managed_agent_ids = list({managed.agent_id for managed in managed_agents} | set(bindings))
    external_bindings = (
        db.query(models.ExternalGatewayAgentBinding)
        .filter(models.ExternalGatewayAgentBinding.managed_agent_id.in_(managed_agent_ids))
        .order_by(models.ExternalGatewayAgentBinding.id.desc())
        .all()
        if managed_agent_ids
        else []
    )
    external_bindings_by_agent: dict[str, list[models.ExternalGatewayAgentBinding]] = {}
    for binding in external_bindings:
        external_bindings_by_agent.setdefault(binding.managed_agent_id, []).append(binding)
    for discovery_id, local_rows in discovery_bindings.items():
        for local in local_rows:
            if local.managed_agent_id and local.managed_agent_id != discovery_id:
                linked = external_bindings_by_agent.get(local.managed_agent_id, [])
                external_bindings_by_agent.setdefault(discovery_id, []).extend(
                    binding for binding in linked if binding.client_id == local.client_id
                )
    external_gateway_ids = {binding.gateway_id for binding in external_bindings}
    external_gateways_by_id = {
        gateway.id: gateway
        for gateway in (
            db.query(models.ExternalAIGateway)
            .filter(models.ExternalAIGateway.id.in_(external_gateway_ids))
            .all()
            if external_gateway_ids
            else []
        )
    }

    rows: list[schemas.AgentAssetResponse] = []
    for managed in managed_agents:
        response = _agent_response(db, managed)
        instance_bindings = discovery_bindings if managed.origin_type == "client_discovery" else bindings
        instances = [
            _asset_instance(
                clients_by_id[local.client_id],
                local,
                skills_by_agent.get((local.client_id, local.agent_type), []),
            )
            for local in instance_bindings.get(managed.agent_id, [])
            if local.client_id in clients_by_id
        ]
        online_count = sum(instance.client_status == "online" for instance in instances)
        last_seen = max((instance.client_last_seen_at for instance in instances), default=None)
        reported_gateway = (
            _reported_external_gateway(
                managed.agent_id,
                instances,
                external_bindings_by_agent,
                external_gateways_by_id,
            )
            if response.origin_type == "client_discovery"
            else None
        )
        rows.append(
            schemas.AgentAssetResponse(
                asset_key=f"managed:{managed.id}",
                managed_agent_pk=managed.id,
                agent_id=response.agent_id,
                name=response.name,
                origin_type=response.origin_type,
                department_group_id=response.department_group_id,
                department_name=response.department_name,
                owner=response.owner,
                description=response.description,
                channel=response.channel,
                status=response.status,
                client_status=("online" if online_count else "offline") if instances else (
                    "not_detected" if managed.origin_type == "client_discovery" else None
                ),
                default_model=response.default_model,
                default_model_source=response.default_model_source,
                external_gateway_id=reported_gateway.id if reported_gateway else response.external_gateway_id,
                external_gateway_name=reported_gateway.name if reported_gateway else response.external_gateway_name,
                skill_names=response.skill_names,
                discovered_skill_count=sum(len(instance.skills) for instance in instances),
                prompt_names=response.prompt_names,
                runtime_token_id=response.runtime_token_id,
                runtime_token_name=response.runtime_token_name,
                created_by=response.created_by,
                created_at=response.created_at,
                updated_at=response.updated_at,
                last_seen_at=last_seen,
                instance_count=len(instances),
                online_instance_count=online_count,
                instances=instances,
            )
        )

    return rows


def _matches_asset_query(row: schemas.AgentAssetResponse, query: str) -> bool:
    values = [row.agent_id, row.name, row.owner or "", row.department_name or "", row.channel or ""]
    for instance in row.instances:
        values.extend((instance.client_id, instance.client_name, instance.hostname, instance.local_agent_id))
    return query.lower() in " ".join(values).lower()


def _validate_external_model_selection(
    db: Session,
    *,
    agent_id: str,
    status: str,
    source: str,
    gateway_id: int | None,
    model_name: str | None,
) -> models.ExternalAIGateway | None:
    if source == "internal":
        if gateway_id is not None:
            raise ApiError(
                422,
                "agent.external_gateway_not_applicable",
                "使用内置模型网关时不能选择外部 AI 网关",
                "An external AI gateway cannot be selected for the built-in model source",
            )
        return None
    if gateway_id is None:
        raise ApiError(422, "agent.external_gateway_required", "请选择外部 AI 网关", "Select an external AI gateway")
    gateway = db.get(models.ExternalAIGateway, gateway_id)
    if not gateway or not gateway.enabled:
        raise ApiError(404, "external_gateway.not_available", "外部 AI 网关不存在或未启用", "External AI gateway is missing or disabled")
    if status == "draft":
        return gateway
    if not model_name:
        raise ApiError(422, "agent.external_model_required", "请选择外部网关模型", "Select an external gateway model")
    binding = db.query(models.ExternalGatewayAgentBinding).filter_by(
        gateway_id=gateway_id,
        managed_agent_id=agent_id,
        status="active",
    ).first()
    if not binding:
        raise ApiError(
            409,
            "agent.external_binding_required",
            "请先注册外部 Agent 并获取可用模型",
            "Register the external Agent and load its available models first",
        )
    if model_name not in {item.get("id") for item in _json_models(binding.available_models_json)}:
        raise ApiError(422, "agent.external_model_unavailable", "选择的外部模型当前不可用", "The selected external model is unavailable")
    return gateway


def _json_models(value: str | None) -> list[dict]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _remove_unused_external_bindings(
    db: Session,
    *,
    agent_id: str,
    keep_gateway_id: int | None,
) -> None:
    bindings = db.query(models.ExternalGatewayAgentBinding).filter_by(managed_agent_id=agent_id).all()
    for binding in bindings:
        if keep_gateway_id is not None and binding.gateway_id == keep_gateway_id:
            continue
        if binding.status != "deleted":
            delete_binding_remote(db, binding)
        db.delete(binding)


@router.get("", response_model=list[schemas.ManagedAgentResponse])
async def list_agents(
    department_group_id: int | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    query = _owned_agents(db, current_user)
    if department_group_id is not None:
        query = query.filter(models.ManagedAgent.department_group_id == department_group_id)
    if status:
        query = query.filter(models.ManagedAgent.status == status)
    if q:
        keyword = f"%{q.strip()}%"
        query = query.filter(
            (models.ManagedAgent.agent_id.like(keyword))
            | (models.ManagedAgent.name.like(keyword))
            | (models.ManagedAgent.owner.like(keyword))
        )
    rows = query.order_by(models.ManagedAgent.id.asc()).all()
    return [_agent_response(db, row) for row in rows]


@router.get("/assets", response_model=schemas.AgentAssetListResponse)
async def list_agent_assets(
    origin: str | None = Query(None, pattern="^(platform|client_discovery)$"),
    department_group_id: int | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    all_rows = _asset_rows(db, current_user)
    stats = {
        "total": len(all_rows),
        "platform": sum(row.origin_type == "platform" for row in all_rows),
        "client_discovery": sum(row.origin_type == "client_discovery" for row in all_rows),
    }
    rows = all_rows
    if origin:
        rows = [row for row in rows if row.origin_type == origin]
    if department_group_id is not None:
        rows = [row for row in rows if row.department_group_id == department_group_id]
    if status in {"online", "offline", "not_detected"}:
        rows = [row for row in rows if row.client_status == status]
    elif status:
        rows = [row for row in rows if row.status == status]
    if q and q.strip():
        rows = [row for row in rows if _matches_asset_query(row, q.strip())]
    rows.sort(key=lambda row: row.updated_at or datetime.min, reverse=True)
    return schemas.AgentAssetListResponse(items=rows, stats=stats)


@router.post("", response_model=schemas.ManagedAgentResponse)
async def create_agent(
    body: schemas.ManagedAgentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    _ensure_department(db, body.department_group_id)
    if db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == body.agent_id).first():
        raise HTTPException(status_code=400, detail="智能体 ID 已存在")
    _validate_external_model_selection(
        db,
        agent_id=body.agent_id,
        status=body.status,
        source=body.default_model_source,
        gateway_id=body.external_gateway_id,
        model_name=body.default_model,
    )
    row = models.ManagedAgent(
        agent_id=body.agent_id,
        name=body.name,
        department_group_id=body.department_group_id,
        owner=body.owner,
        description=body.description,
        channel=body.channel,
        status=body.status,
        default_model=body.default_model,
        default_model_source=body.default_model_source,
        external_gateway_id=body.external_gateway_id,
        origin_type="platform",
        skill_names_json=_dump_list(body.skill_names),
        prompt_names_json=_dump_list(body.prompt_names),
        created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _agent_response(db, row)


@router.put("/{agent_pk}", response_model=schemas.ManagedAgentResponse)
async def update_agent(
    agent_pk: int,
    body: schemas.ManagedAgentUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _owned_agents(db, current_user).filter(models.ManagedAgent.id == agent_pk).first()
    if not row:
        raise HTTPException(status_code=404, detail="智能体不存在")
    data = body.model_dump(exclude_unset=True)
    if "department_group_id" in data:
        _ensure_department(db, data["department_group_id"])
    if row.origin_type == "client_discovery":
        if data.get("agent_id", row.agent_id) != row.agent_id or data.get("channel", row.channel) != row.channel:
            raise ApiError(
                409,
                "agent.client_identity_immutable",
                "客户端自动登记的 Agent ID 和类型不能修改",
                "The ID and type of a Client-registered Agent cannot be changed",
            )
    if "agent_id" in data:
        existing = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == data["agent_id"]).first()
        if existing and existing.id != row.id:
            raise HTTPException(status_code=400, detail="智能体 ID 已存在")
        has_credentials = db.query(models.AccessToken).filter(models.AccessToken.bound_agent_id == row.agent_id).first()
        has_external_binding = db.query(models.ExternalGatewayAgentBinding).filter_by(managed_agent_id=row.agent_id).first()
        if data["agent_id"] != row.agent_id and (has_credentials or has_external_binding):
            raise ApiError(
                409,
                "agent.id_bound_to_credentials",
                "智能体已绑定运行凭证或外部网关身份，不能修改智能体 ID",
                "The Agent ID cannot be changed after runtime credentials or an external gateway identity have been bound",
            )
    source = data.get("default_model_source", row.default_model_source or "internal")
    gateway_id = data.get("external_gateway_id", row.external_gateway_id)
    if source == "internal":
        gateway_id = None
        data["external_gateway_id"] = None
    model_name = data.get("default_model", row.default_model)
    status = data.get("status", row.status)
    _validate_external_model_selection(
        db,
        agent_id=data.get("agent_id", row.agent_id),
        status=status,
        source=source,
        gateway_id=gateway_id,
        model_name=model_name,
    )
    data.pop("runtime_token_id", None)
    data.pop("runtime_token_name", None)
    if "skill_names" in data:
        row.skill_names_json = _dump_list(data.pop("skill_names"))
    if "prompt_names" in data:
        row.prompt_names_json = _dump_list(data.pop("prompt_names"))
    for field, value in data.items():
        setattr(row, field, value)
    _remove_unused_external_bindings(
        db,
        agent_id=row.agent_id,
        keep_gateway_id=gateway_id if source == "external_gateway" else None,
    )
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _agent_response(db, row)


@router.post("/{agent_pk}/external-model-catalog")
async def prepare_external_model_catalog(
    agent_pk: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _owned_agents(db, current_user).filter(models.ManagedAgent.id == agent_pk).first()
    if not row:
        raise ApiError(404, "agent.not_found", "智能体不存在", "Agent not found")
    try:
        gateway_id = int(body.get("gateway_id"))
    except (TypeError, ValueError):
        raise ApiError(422, "agent.external_gateway_required", "请选择外部 AI 网关", "Select an external AI gateway")
    gateway = db.get(models.ExternalAIGateway, gateway_id)
    if not gateway or not gateway.enabled:
        raise ApiError(404, "external_gateway.not_available", "外部 AI 网关不存在或未启用", "External AI gateway is missing or disabled")
    binding = ensure_binding(db, gateway, row, client_id=None)
    catalog = binding_models(db, gateway, binding)
    db.commit()
    return {
        "gateway_id": gateway.id,
        "gateway_name": gateway.name,
        "external_agent_id": binding.external_agent_id,
        "key_id": binding.key_id,
        "binding_status": binding.status,
        "models": catalog,
    }


@router.delete("/{agent_pk}")
async def delete_agent(
    agent_pk: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _owned_agents(db, current_user).filter(models.ManagedAgent.id == agent_pk).first()
    if not row:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if row.origin_type == "client_discovery":
        raise ApiError(
            409,
            "agent.client_managed",
            "该智能体由客户端自动登记，请在所属客户端管理本机 Agent",
            "This Agent is registered automatically and managed by its Client",
        )
    if db.query(models.AccessToken).filter(models.AccessToken.bound_agent_id == row.agent_id).first():
        raise ApiError(
            409,
            "agent.credentials_still_bound",
            "智能体仍绑定接入凭证，请先吊销并删除相关凭证",
            "Revoke and delete credentials bound to this Agent before deleting it",
        )
    bindings = db.query(models.ExternalGatewayAgentBinding).filter_by(managed_agent_id=row.agent_id).all()
    for binding in bindings:
        if binding.status != "deleted":
            delete_binding_remote(db, binding)
        db.delete(binding)
    for local in db.query(models.ClientAgent).filter(models.ClientAgent.managed_agent_id == row.agent_id).all():
        local.managed_agent_id = None
        local.takeover_status = "discovered"
    db.delete(row)
    db.commit()
    return {"ok": True}
