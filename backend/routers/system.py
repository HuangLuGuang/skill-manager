import os
from ..aidr_skill_contract import SkillAuditPolicy
import json
import shutil
from datetime import datetime, timedelta
from typing import List, Optional

import psutil
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from .. import auth, models, iam
from ..api_errors import ApiError
from ..config import settings
from ..feature_flags import baseline_summary, feature_flags
from ..sqlite_db import get_db
from ..task_runtime import collect_system_metric_snapshot, persist_system_metric


router = APIRouter(prefix="/system", tags=["system"])
LOGO_DIR = settings.UPLOADS_DIR
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class BrandingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_name_zh: str = Field(default="智能体生命周期管理系统", min_length=1, max_length=80)
    system_name_en: str = Field(default="Agent Manager", min_length=1, max_length=80)
    company_name: str = Field(default="", max_length=120)

    @field_validator("system_name_zh", "system_name_en")
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError("System name cannot be blank")
        return value.strip()


def branding_config(db):
    row = db.get(models.SystemConfig, "system_branding")
    return BrandingConfig(**json.loads(row.value)).model_dump() if row else BrandingConfig().model_dump()


@router.get("/branding")
async def get_branding(db: Session = Depends(get_db)):
    return {**branding_config(db), **await get_logo_info()}


@router.put("/branding")
async def update_branding(body: BrandingConfig, request: Request, db: Session = Depends(get_db),
                          user=Depends(iam.require("settings:update"))):
    before = branding_config(db)
    values = body.model_dump()
    row = db.get(models.SystemConfig, "system_branding")
    if row is None:
        row = models.SystemConfig(key="system_branding", value="{}")
        db.add(row)
    row.value = json.dumps(values, ensure_ascii=False)
    iam.audit(db, request, user, "settings", "update", "system_branding", before=before, after=values)
    iam.commit(db)
    return {**values, **await get_logo_info()}


class DiskUsage(BaseModel):
    total: int
    used: int
    free: int
    percent: float


class MemoryUsage(BaseModel):
    total: int
    available: int
    used: int
    percent: float


class CpuUsage(BaseModel):
    percent: float
    count: int


class SystemInfo(BaseModel):
    disk: DiskUsage
    memory: MemoryUsage
    cpu: CpuUsage
    data_dir: str
    data_dir_size: int


class SystemCapabilities(BaseModel):
    features: dict[str, bool]
    baseline: dict


class MetricRecord(BaseModel):
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    disk_percent: float


class MetricsHistoryResponse(BaseModel):
    data: List[MetricRecord]


class FileInfo(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    modified_time: str
    can_delete: bool


class FileListResponse(BaseModel):
    current_path: str
    parent_path: Optional[str]
    items: List[FileInfo]
    total_size: int


def get_dir_size(path: str) -> int:
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total += os.path.getsize(filepath)
                except OSError:
                    pass
    except OSError:
        pass
    return total


def format_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


@router.get("/info", response_model=SystemInfo)
async def get_system_info(current_user: models.User = Depends(auth.get_current_admin_user)):
    data_dir = settings.DATA_DIR
    os.makedirs(data_dir, exist_ok=True)
    try:
        disk = shutil.disk_usage(data_dir)
    except OSError:
        disk = shutil.disk_usage("/")
    memory = psutil.virtual_memory()
    cpu_percent, _, _ = collect_system_metric_snapshot()
    return SystemInfo(
        disk=DiskUsage(
            total=disk.total,
            used=disk.used,
            free=disk.free,
            percent=(disk.used / disk.total) * 100 if disk.total else 0,
        ),
        memory=MemoryUsage(
            total=memory.total,
            available=memory.available,
            used=memory.used,
            percent=memory.percent,
        ),
        cpu=CpuUsage(percent=cpu_percent, count=psutil.cpu_count() or 0),
        data_dir=data_dir,
        data_dir_size=get_dir_size(data_dir),
    )


@router.get("/capabilities", response_model=SystemCapabilities)
async def get_system_capabilities(current_user: models.User = Depends(auth.get_current_active_user)):
    return SystemCapabilities(
        features=feature_flags(),
        baseline=baseline_summary(),
    )


@router.post("/metrics/collect")
async def collect_metrics(
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    cpu_percent, memory_percent, disk_percent = persist_system_metric()
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="采集系统指标",
            target="system_metrics",
            details=f"CPU={cpu_percent:.1f}%, MEM={memory_percent:.1f}%, DISK={disk_percent:.1f}%",
        )
    )
    db.commit()
    return {"status": "success"}


@router.get("/metrics/history", response_model=MetricsHistoryResponse)
async def get_metrics_history(
    hours: int = Query(default=24, ge=1, le=168),
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    since = datetime.now() - timedelta(hours=hours)
    rows = (
        db.query(models.SystemMetric)
        .filter(models.SystemMetric.timestamp >= since)
        .order_by(models.SystemMetric.timestamp.asc())
        .all()
    )
    return {
        "data": [
            MetricRecord(
                timestamp=row.timestamp,
                cpu_percent=row.cpu_percent,
                memory_percent=row.memory_percent,
                disk_percent=row.disk_percent,
            )
            for row in rows
        ]
    }


@router.get("/files", response_model=FileListResponse)
async def list_files(
    path: str = Query("", description="Relative path within DATA_DIR"),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    data_dir = os.path.normpath(settings.DATA_DIR)
    os.makedirs(data_dir, exist_ok=True)
    full_path = os.path.normpath(os.path.join(data_dir, path)) if path else data_dir
    if not full_path.startswith(data_dir):
        raise HTTPException(status_code=403, detail="Access denied: path outside DATA_DIR")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Path not found")
    if not os.path.isdir(full_path):
        raise HTTPException(status_code=400, detail="Path is not a directory")

    items = []
    total_size = 0
    for entry in os.scandir(full_path):
        stat = entry.stat()
        is_dir = entry.is_dir()
        size = get_dir_size(entry.path) if is_dir else stat.st_size
        total_size += size
        items.append(
            FileInfo(
                name=entry.name,
                path=os.path.relpath(entry.path, data_dir),
                is_dir=is_dir,
                size=size,
                modified_time=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                can_delete=not is_dir,
            )
        )
    items.sort(key=lambda item: (not item.is_dir, item.name.lower()))
    parent_path = os.path.dirname(path) if path else None
    if parent_path == ".":
        parent_path = ""
    return FileListResponse(
        current_path=path or "",
        parent_path=parent_path,
        items=items,
        total_size=total_size,
    )


@router.delete("/files")
async def delete_file(
    path: str = Query(..., description="Relative path to file within DATA_DIR"),
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    data_dir = os.path.normpath(settings.DATA_DIR)
    full_path = os.path.normpath(os.path.join(data_dir, path))
    if not full_path.startswith(data_dir):
        raise HTTPException(status_code=403, detail="Access denied: path outside DATA_DIR")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    if os.path.isdir(full_path):
        raise HTTPException(status_code=400, detail="Cannot delete directories")

    file_size = os.path.getsize(full_path)
    os.remove(full_path)
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="删除文件",
            target=path,
            details=f"文件大小: {format_size(file_size)}",
        )
    )
    db.commit()
    return {"status": "success"}


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError(400, "branding.invalid_logo_type", "请上传 PNG、JPEG、GIF 或 WebP 图片", "Upload a PNG, JPEG, GIF, or WebP image")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise ApiError(400, "branding.logo_too_large", "文件大小不能超过 5MB", "The image must not exceed 5 MB")
    valid = {".png": content.startswith(b"\x89PNG\r\n\x1a\n"), ".jpg": content.startswith(b"\xff\xd8\xff"),
             ".jpeg": content.startswith(b"\xff\xd8\xff"), ".gif": content[:6] in {b"GIF87a", b"GIF89a"},
             ".webp": content[:4] == b"RIFF" and content[8:12] == b"WEBP"}
    if not valid[ext]:
        raise ApiError(400, "branding.invalid_logo_content", "图片内容与文件格式不符", "Image content does not match its file type")
    os.makedirs(LOGO_DIR, exist_ok=True)
    for name in os.listdir(LOGO_DIR):
        if name.startswith("custom_logo"):
            os.remove(os.path.join(LOGO_DIR, name))
    filename = f"custom_logo{ext}"
    with open(os.path.join(LOGO_DIR, filename), "wb") as f:
        f.write(content)
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="上传Logo",
            target=file.filename,
            details=f"文件大小: {format_size(len(content))}",
        )
    )
    db.commit()
    return {"status": "success", "logo_url": f"/uploads/{filename}"}


@router.get("/logo")
async def get_logo_info():
    if os.path.exists(LOGO_DIR):
        for name in os.listdir(LOGO_DIR):
            if name.startswith("custom_logo"):
                return {"has_custom_logo": True, "logo_url": f"/uploads/{name}"}
    return {"has_custom_logo": False, "logo_url": "/logo.png"}


@router.delete("/logo")
async def delete_logo(
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    deleted = False
    if os.path.exists(LOGO_DIR):
        for name in os.listdir(LOGO_DIR):
            if name.startswith("custom_logo"):
                os.remove(os.path.join(LOGO_DIR, name))
                deleted = True
    if deleted:
        db.add(
            models.OperationLog(
                username=current_user.username,
                action="删除Logo",
                target="custom_logo",
                details="恢复默认Logo",
            )
        )
        db.commit()
    return {"status": "success"}


from ..aidr_content import AuditLifecycle, CaptureScope


class AidrRedactionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    version: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    capture: CaptureScope | None = None
    lifecycle: AuditLifecycle | None = None
    skill_audit: SkillAuditPolicy | None = None


@router.get("/aidr-redaction")
def get_aidr_redaction(db: Session = Depends(get_db), user=Depends(iam.require("settings:view"))):
    from ..aidr_policy import current
    return {**current(db), "can_edit": user.role in {"admin", "super_admin"} and "settings:update" in iam.permission_codes(db, user)}


@router.put("/aidr-redaction")
def update_aidr_redaction(body: AidrRedactionUpdate, request: Request, db: Session = Depends(get_db), user=Depends(iam.require("settings:update"))):
    from ..aidr_policy import save
    return save(db, body, user, request)
