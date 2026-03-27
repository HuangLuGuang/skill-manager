import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..sqlite_db import get_db


router = APIRouter(prefix="/config", tags=["config"])


DEFAULT_LOG_PARSE = {
    "tenant": "default",
    "normalize_fields": ["timestamp", "src_ip", "path", "status"],
    "header_fields": ["user_agent", "referer"],
    "body_fields": ["billId"],
    "computed_fields": ["request_length"],
    "fields": [],
    "phone_no_field": ["billId"],
    "phone_no_field_pos": "body",
    "static_resource_extensions": [".js", ".css", ".png", ".jpg", ".svg"],
    "botgate_log_prefix": "botgate_access.log-",
}

DEFAULT_MODEL_CONFIG = schemas.ModelConfigUpdate().model_dump()


def load_config(db: Session, key: str, default: dict) -> dict:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    if not row:
        value = default.copy()
        value["fields"] = (
            value.get("normalize_fields", [])
            + value.get("body_fields", [])
            + value.get("header_fields", [])
            + value.get("computed_fields", [])
        )
        return value
    data = json.loads(row.value)
    if "fields" in default:
        data["fields"] = (
            data.get("normalize_fields", [])
            + data.get("body_fields", [])
            + data.get("header_fields", [])
            + data.get("computed_fields", [])
        )
    return data


def save_config(db: Session, key: str, payload: dict, description: str) -> None:
    row = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
    value = json.dumps(payload, ensure_ascii=False)
    if row:
        row.value = value
        row.description = description
    else:
        db.add(models.SystemConfig(key=key, value=value, description=description))


@router.get("/log-parse", response_model=schemas.LogParseConfigUpdate)
async def get_log_parse_config(
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    return load_config(db, "log_parse_config", DEFAULT_LOG_PARSE)


@router.post("/log-parse")
async def update_log_parse_config(
    config_update: schemas.LogParseConfigUpdate,
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    payload = config_update.model_dump()
    payload["fields"] = (
        payload.get("normalize_fields", [])
        + payload.get("body_fields", [])
        + payload.get("header_fields", [])
        + payload.get("computed_fields", [])
    )
    save_config(db, "log_parse_config", payload, "日志解析配置")
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="更新配置",
            target="日志解析配置",
            details="已保存日志解析配置",
        )
    )
    db.commit()
    return {"status": "success"}


@router.get("/model", response_model=schemas.ModelConfigUpdate)
async def get_model_config(
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    return load_config(db, "model_config", DEFAULT_MODEL_CONFIG)


@router.post("/model")
async def update_model_config(
    config_update: schemas.ModelConfigUpdate,
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    payload = config_update.model_dump()
    save_config(db, "model_config", payload, "模型配置")
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="更新配置",
            target="模型配置",
            details="已保存模型配置",
        )
    )
    db.commit()
    return {"status": "success"}
