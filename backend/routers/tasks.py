from datetime import datetime

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..sqlite_db import get_db
from ..task_runtime import (
    TASK_FUNC_INFO,
    TASK_FUNCTIONS,
    init_default_tasks,
    start_command_task,
    start_function_task,
    stop_execution,
)


router = APIRouter(prefix="/tasks", tags=["tasks"])


def serialize_task(task: models.ScheduledTask, db: Session) -> dict:
    latest = (
        db.query(models.TaskExecution)
        .filter(models.TaskExecution.task_id == task.id)
        .order_by(models.TaskExecution.id.desc())
        .first()
    )
    next_run_at = None
    if task.cron_expr and task.enabled:
        try:
            next_run_at = croniter(task.cron_expr, datetime.now()).get_next(datetime)
        except Exception:
            next_run_at = None
    return {
        "id": task.id,
        "name": task.name,
        "display_name": task.display_name,
        "description": task.description,
        "task_type": task.task_type,
        "task_func": task.task_func,
        "command": task.command,
        "cron_expr": task.cron_expr,
        "enabled": task.enabled,
        "last_run_at": task.last_run_at,
        "created_at": task.created_at,
        "latest_execution_status": latest.status if latest else None,
        "next_run_at": next_run_at,
    }


@router.get("/available-functions")
async def get_available_functions(current_user: models.User = Depends(auth.get_current_admin_user)):
    return list(TASK_FUNC_INFO.values())


@router.get("", response_model=list[schemas.ScheduledTaskResponse])
async def get_tasks(
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    init_default_tasks(db)
    tasks = db.query(models.ScheduledTask).order_by(models.ScheduledTask.id).all()
    return [serialize_task(task, db) for task in tasks]


@router.post("", response_model=schemas.ScheduledTaskResponse)
async def create_task(
    task_create: schemas.ScheduledTaskCreate,
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    exists = db.query(models.ScheduledTask).filter(models.ScheduledTask.name == task_create.name).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"Task with name '{task_create.name}' already exists")
    if task_create.task_type == "function" and task_create.task_func not in TASK_FUNCTIONS:
        raise HTTPException(status_code=400, detail="Invalid task function")
    if task_create.task_type == "command" and not task_create.command:
        raise HTTPException(status_code=400, detail="Command is required for command type task")
    task = models.ScheduledTask(**task_create.model_dump())
    db.add(task)
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="创建任务",
            target=task.display_name,
            details=f"创建任务: {task.name}",
        )
    )
    db.commit()
    db.refresh(task)
    return serialize_task(task, db)


@router.put("/{task_id}", response_model=schemas.ScheduledTaskResponse)
async def update_task(
    task_id: int,
    task_update: schemas.ScheduledTaskUpdate,
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    task = db.query(models.ScheduledTask).filter(models.ScheduledTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = task_update.model_dump(exclude_unset=True)
    if payload.get("task_type") == "function" and payload.get("task_func") and payload["task_func"] not in TASK_FUNCTIONS:
        raise HTTPException(status_code=400, detail="Invalid task function")
    for key, value in payload.items():
        setattr(task, key, value)
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="更新任务",
            target=task.display_name,
            details=str(payload),
        )
    )
    db.commit()
    db.refresh(task)
    return serialize_task(task, db)


@router.post("/{task_id}/run")
async def run_task(
    task_id: int,
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    task = db.query(models.ScheduledTask).filter(models.ScheduledTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    execution = models.TaskExecution(
        task_id=task.id,
        task_name=task.name,
        status="pending",
        created_at=datetime.now(),
    )
    task.last_run_at = datetime.now()
    db.add(execution)
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="执行任务",
            target=task.display_name,
            details=f"execution_id={execution.id if execution.id else 'pending'}",
        )
    )
    db.commit()
    db.refresh(execution)
    if task.task_type == "function":
        start_function_task(execution.id, task.task_func)
    else:
        start_command_task(execution.id, task.command)
    return {"status": "started", "execution_id": execution.id}


@router.post("/maintenance/backfill-stats")
async def backfill_stats(
    payload: schemas.StatsBackfillRequest,
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    execution = models.TaskExecution(
        task_id=0,
        task_name="backfill_stats",
        status="pending",
        created_at=datetime.now(),
    )
    db.add(execution)
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="执行模板维护任务",
            target="backfill_stats",
            details=f"days={payload.days}",
        )
    )
    db.commit()
    db.refresh(execution)
    start_function_task(execution.id, "sample_maintenance_task", days=payload.days)
    return {"status": "started", "execution_id": execution.id}


@router.post("/{task_id}/stop")
async def stop_task(
    task_id: int,
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    execution = (
        db.query(models.TaskExecution)
        .filter(
            models.TaskExecution.task_id == task_id,
            models.TaskExecution.status.in_(["pending", "running"]),
        )
        .order_by(models.TaskExecution.id.desc())
        .first()
    )
    if not execution:
        raise HTTPException(status_code=404, detail="No running or pending execution found")
    if not stop_execution(execution.id):
        execution.status = "revoked"
        execution.finished_at = datetime.now()
        db.commit()
    db.add(
        models.OperationLog(
            username=current_user.username,
            action="停止任务",
            target=execution.task_name,
            details=f"execution_id={execution.id}",
        )
    )
    db.commit()
    return {"status": "revoked", "execution_id": execution.id}


@router.get("/executions/list", response_model=list[schemas.TaskExecutionResponse])
async def get_executions(
    task_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.TaskExecution)
    if task_id is not None:
        query = query.filter(models.TaskExecution.task_id == task_id)
    return query.order_by(models.TaskExecution.id.desc()).limit(limit).all()


@router.get("/executions/{execution_id}/logs", response_model=schemas.ExecutionLogsResponse)
async def get_execution_logs(
    execution_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: models.User = Depends(auth.get_current_admin_user),
    db: Session = Depends(get_db),
):
    execution = db.query(models.TaskExecution).filter(models.TaskExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    lines = (execution.logs or "").splitlines()
    total = len(lines)
    end = min(offset + limit, total)
    return {
        "logs": "\n".join(lines[offset:end]),
        "total_lines": total,
        "has_more": end < total,
    }
