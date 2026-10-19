import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models
from ..api_errors import ApiError
from ..external_access import OPENAPI_SCOPES
from ..sqlite_db import get_db

router = APIRouter(prefix="/external-access", tags=["external-access"])
openapi_router = APIRouter(prefix="/openapi/v1", tags=["external-access"])


class DepartmentMapping(BaseModel):
    department_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    group_id: int = Field(gt=0)


class PlatformBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    departments: list[DepartmentMapping] = Field(default_factory=list, max_length=200)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


class PlatformCreate(PlatformBody):
    platform_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")


def _platform(row):
    return {"platform_id": row.platform_id, "name": row.name, "enabled": row.enabled,
            "departments": json.loads(row.departments_json), "created_at": row.created_at, "updated_at": row.updated_at}


def _validate_departments(db, departments):
    if len({d.department_id for d in departments}) != len(departments):
        raise ApiError(400, "external_access.department_duplicate", "部门编码不能重复", "Department codes must be unique")
    groups = {d.group_id for d in departments}
    if db.query(models.UserGroup).filter(models.UserGroup.id.in_(groups)).count() != len(groups):
        raise ApiError(400, "external_access.department_invalid", "部门映射的用户组不存在", "A mapped user group does not exist")


@router.get("/options")
def options(db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return {"scopes": OPENAPI_SCOPES, "groups": [{"id": g.id, "name": g.name} for g in db.query(models.UserGroup).order_by(models.UserGroup.name).all()]}


@router.get("/platforms")
def list_platforms(db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return {"items": [_platform(p) for p in db.query(models.ExternalPlatform).order_by(models.ExternalPlatform.created_at.desc()).all()]}


@router.post("/platforms", status_code=201)
def create_platform(body: PlatformCreate, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    _validate_departments(db, body.departments)
    row = models.ExternalPlatform(platform_id=body.platform_id, name=body.name, enabled=body.enabled,
        departments_json=json.dumps([d.model_dump() for d in body.departments]), created_by=user.username)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "external_access.platform_exists", "接入方标识已存在", "The partner identifier already exists")
    return _platform(row)


@router.put("/platforms/{platform_id}")
def update_platform(platform_id: str, body: PlatformBody, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    row = db.get(models.ExternalPlatform, platform_id)
    if not row:
        raise ApiError(404, "external_access.platform_not_found", "接入方不存在", "Integration partner not found")
    _validate_departments(db, body.departments)
    previous = {d["department_id"]: d["group_id"] for d in json.loads(row.departments_json)}
    next_mapping = {d.department_id: d.group_id for d in body.departments}
    # An existing code identifies a department across credentials and business records.
    if any(code in next_mapping and next_mapping[code] != group for code, group in previous.items()):
        raise ApiError(409, "external_access.department_rebind", "已有部门编码的用户组不能更换，请使用新的部门编码", "Use a new department code to map a different user group")
    removed = previous.keys() - next_mapping.keys()
    if removed:
        for token in db.query(models.AccessToken).filter_by(platform_id=platform_id).all():
            if token.status != "revoked" and removed.intersection(json.loads(token.allowed_department_ids_json)):
                raise ApiError(409, "external_access.department_in_use", "部门仍被凭证使用，请先调整凭证授权", "Update credential authorization before removing a referenced department")
    row.name, row.enabled = body.name, body.enabled
    row.departments_json = json.dumps([d.model_dump() for d in body.departments])
    row.updated_at = datetime.utcnow()
    db.commit()
    return _platform(row)


def _record(row):
    return {column.name: getattr(row, column.name) for column in models.ExternalApiRequest.__table__.columns}


@router.get("/requests")
def list_requests(platform_id: str | None = None, token_id: int | None = None, request_id: str | None = None,
                  method: str | None = Query(None, pattern="^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$"),
                  route: str | None = None, source_ip: str | None = None,
                  business_request_id: str | None = None, department_id: str | None = None,
                  resource_id: str | None = None, status_code: int | None = Query(None, ge=100, le=599),
                  outcome: str | None = Query(None, pattern="^(success|failed|pending)$"),
                  started_at: datetime | None = None, ended_at: datetime | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    query = db.query(models.ExternalApiRequest)
    if request_id is not None:
        query = query.filter((models.ExternalApiRequest.request_id == request_id) | (models.ExternalApiRequest.client_request_id == request_id))
    for key, value in {"platform_id": platform_id, "token_id": token_id, "method": method, "route": route, "source_ip": source_ip,
                       "resource_id": resource_id, "status_code": status_code, "business_request_id": business_request_id, "department_id": department_id}.items():
        if value is not None:
            query = query.filter(getattr(models.ExternalApiRequest, key) == value)
    if outcome == "success":
        query = query.filter(models.ExternalApiRequest.status_code < 400)
    elif outcome == "failed":
        query = query.filter(models.ExternalApiRequest.status_code >= 400)
    elif outcome == "pending":
        query = query.filter(models.ExternalApiRequest.status_code.is_(None))
    def utc(value):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value
    started_at, ended_at = utc(started_at), utc(ended_at)
    if started_at and ended_at and started_at > ended_at:
        raise ApiError(400, "external_access.date_range_invalid", "开始时间不能晚于结束时间", "Start time must not be later than end time")
    if started_at:
        query = query.filter(models.ExternalApiRequest.created_at >= started_at)
    if ended_at:
        query = query.filter(models.ExternalApiRequest.created_at <= ended_at)
    return {"total": query.count(), "items": [_record(row) for row in query.order_by(models.ExternalApiRequest.id.desc()).offset((page - 1) * page_size).limit(page_size).all()]}


@router.get("/requests/{request_id}")
def get_request(request_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    row = db.query(models.ExternalApiRequest).filter_by(request_id=request_id).first()
    if not row:
        raise ApiError(404, "external_access.request_not_found", "调用记录不存在", "Request record not found")
    return _record(row)


@openapi_router.get("/access-context")
def access_context(request: Request):
    """Verify connectivity and current authorization before business integration."""
    context = request.state.external_access
    return {"request_id": request.state.request_id, "platform_id": context.platform_id,
            "scopes": context.scopes, "department_ids": sorted(context.departments)}
