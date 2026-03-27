import os
import shutil
from datetime import datetime, timedelta
from typing import List, Optional

import psutil
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import auth, models
from ..config import settings
from ..sqlite_db import get_db
from ..task_runtime import collect_system_metric_snapshot, persist_system_metric


router = APIRouter(prefix="/system", tags=["system"])
LOGO_DIR = settings.UPLOADS_DIR
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


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
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件格式")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小不能超过 5MB")
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
