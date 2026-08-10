import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..api_errors import ApiError
from ..sqlite_db import get_db


router = APIRouter(prefix="/agents", tags=["agents"])


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


@router.post("", response_model=schemas.ManagedAgentResponse)
async def create_agent(
    body: schemas.ManagedAgentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    _ensure_department(db, body.department_group_id)
    if db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == body.agent_id).first():
        raise HTTPException(status_code=400, detail="智能体 ID 已存在")
    row = models.ManagedAgent(
        agent_id=body.agent_id,
        name=body.name,
        department_group_id=body.department_group_id,
        owner=body.owner,
        description=body.description,
        channel=body.channel,
        status=body.status,
        default_model=body.default_model,
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
    if "agent_id" in data:
        existing = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == data["agent_id"]).first()
        if existing and existing.id != row.id:
            raise HTTPException(status_code=400, detail="智能体 ID 已存在")
        if data["agent_id"] != row.agent_id and db.query(models.AccessToken).filter(
            models.AccessToken.bound_agent_id == row.agent_id,
        ).first():
            raise ApiError(
                409,
                "agent.id_bound_to_credentials",
                "智能体已签发运行凭证，不能修改智能体 ID",
                "The Agent ID cannot be changed after runtime credentials have been issued",
            )
    data.pop("runtime_token_id", None)
    data.pop("runtime_token_name", None)
    if "skill_names" in data:
        row.skill_names_json = _dump_list(data.pop("skill_names"))
    if "prompt_names" in data:
        row.prompt_names_json = _dump_list(data.pop("prompt_names"))
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return _agent_response(db, row)


@router.delete("/{agent_pk}")
async def delete_agent(
    agent_pk: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _owned_agents(db, current_user).filter(models.ManagedAgent.id == agent_pk).first()
    if not row:
        raise HTTPException(status_code=404, detail="智能体不存在")
    if db.query(models.AccessToken).filter(models.AccessToken.bound_agent_id == row.agent_id).first():
        raise ApiError(
            409,
            "agent.credentials_still_bound",
            "智能体仍绑定接入凭证，请先吊销并删除相关凭证",
            "Revoke and delete credentials bound to this Agent before deleting it",
        )
    db.delete(row)
    db.commit()
    return {"ok": True}
