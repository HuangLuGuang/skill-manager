import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

import psutil
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .sqlite_db import SessionLocal


@dataclass
class RunningTask:
    stop_event: threading.Event
    process: Optional[subprocess.Popen] = None


RUNNING_TASKS: dict[int, RunningTask] = {}
RUNNING_TASKS_LOCK = threading.Lock()


def append_execution_log(execution_id: int, message: str) -> None:
    db = SessionLocal()
    try:
        execution = db.query(models.TaskExecution).filter(models.TaskExecution.id == execution_id).first()
        if not execution:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current = execution.logs or ""
        execution.logs = f"{current}[{timestamp}] {message}\n"
        db.commit()
    finally:
        db.close()


def update_execution_status(execution_id: int, status: str, error: str | None = None) -> None:
    db = SessionLocal()
    try:
        execution = db.query(models.TaskExecution).filter(models.TaskExecution.id == execution_id).first()
        if not execution:
            return
        execution.status = status
        if status == "running" and execution.started_at is None:
            execution.started_at = datetime.now()
        if status in {"success", "failed", "revoked"}:
            execution.finished_at = datetime.now()
        if error:
            execution.error = error
        db.commit()
    finally:
        db.close()


def collect_system_metric_snapshot() -> tuple[float, float, float]:
    data_dir = settings.DATA_DIR
    try:
        disk = shutil.disk_usage(data_dir)
    except (FileNotFoundError, OSError):
        disk = shutil.disk_usage("/")
    disk_percent = (disk.used / disk.total) * 100 if disk.total else 0
    memory = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.1)
    return cpu_percent, memory.percent, disk_percent


def persist_system_metric() -> tuple[float, float, float]:
    cpu_percent, memory_percent, disk_percent = collect_system_metric_snapshot()
    db = SessionLocal()
    try:
        db.add(
            models.SystemMetric(
                timestamp=datetime.now(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                disk_percent=disk_percent,
            )
        )
        cutoff = datetime.now() - timedelta(days=7)
        db.query(models.SystemMetric).filter(models.SystemMetric.timestamp < cutoff).delete()
        db.commit()
    finally:
        db.close()
    return cpu_percent, memory_percent, disk_percent


def sample_maintenance_task(execution_id: int, stop_event: threading.Event, days: int = 7) -> None:
    append_execution_log(execution_id, f"开始执行模板维护任务，范围最近 {days} 天")
    for step in range(1, 4):
        if stop_event.is_set():
            append_execution_log(execution_id, "收到停止信号，任务终止")
            raise InterruptedError("任务被用户停止")
        append_execution_log(execution_id, f"执行步骤 {step}/3")
        time.sleep(1)
    append_execution_log(execution_id, "模板维护任务执行完成")


def collect_system_metrics_task(execution_id: int, stop_event: threading.Event) -> None:
    if stop_event.is_set():
        raise InterruptedError("任务被用户停止")
    cpu_percent, memory_percent, disk_percent = persist_system_metric()
    append_execution_log(
        execution_id,
        f"系统指标已采集: CPU={cpu_percent:.1f}%, 内存={memory_percent:.1f}%, 磁盘={disk_percent:.1f}%",
    )


def run_shell_command_task(execution_id: int, stop_event: threading.Event, command: str) -> None:
    append_execution_log(execution_id, f"开始执行命令: {command}")
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=os.getcwd(),
    )
    with RUNNING_TASKS_LOCK:
        running = RUNNING_TASKS.get(execution_id)
        if running:
            running.process = process

    assert process.stdout is not None
    while True:
        if stop_event.is_set():
            process.terminate()
            append_execution_log(execution_id, "命令执行已终止")
            raise InterruptedError("任务被用户停止")
        line = process.stdout.readline()
        if line:
            append_execution_log(execution_id, line.rstrip())
        if line == "" and process.poll() is not None:
            break

    if process.returncode != 0:
        raise RuntimeError(f"命令执行失败，退出码 {process.returncode}")
    append_execution_log(execution_id, "命令执行完成")


TASK_FUNC_INFO = {
    "sample_maintenance_task": {
        "name": "sample_maintenance_task",
        "display_name": "模板维护任务",
        "description": "示例任务，适合作为接入真实业务任务前的占位实现",
    },
    "collect_system_metrics_task": {
        "name": "collect_system_metrics_task",
        "display_name": "系统指标采集",
        "description": "采集 CPU、内存、磁盘使用率并写入历史记录",
    },
}

TASK_FUNCTIONS: dict[str, Callable[..., None]] = {
    "sample_maintenance_task": sample_maintenance_task,
    "collect_system_metrics_task": collect_system_metrics_task,
}


def init_default_tasks(db: Session) -> None:
    defaults = [
        {
            "name": "system_metrics_collect",
            "display_name": "系统指标采集",
            "description": "采集 CPU、内存、磁盘使用率并存储历史数据",
            "task_func": "collect_system_metrics_task",
            "cron_expr": "*/10 * * * *",
            "enabled": True,
        },
        {
            "name": "starter_maintenance",
            "display_name": "模板维护任务",
            "description": "示例任务，用于替换为真实业务逻辑",
            "task_func": "sample_maintenance_task",
            "cron_expr": "0 2 * * *",
            "enabled": False,
        },
    ]
    for data in defaults:
        exists = db.query(models.ScheduledTask).filter(models.ScheduledTask.name == data["name"]).first()
        if not exists:
            db.add(models.ScheduledTask(**data))
    db.commit()


def _run_task(execution_id: int, runner: Callable[..., None], *args, **kwargs) -> None:
    update_execution_status(execution_id, "running")
    try:
        stop_event = RUNNING_TASKS[execution_id].stop_event
        runner(execution_id, stop_event, *args, **kwargs)
        update_execution_status(execution_id, "success")
    except InterruptedError as exc:
        update_execution_status(execution_id, "revoked", str(exc))
    except Exception as exc:
        append_execution_log(execution_id, f"任务失败: {exc}")
        update_execution_status(execution_id, "failed", str(exc))
    finally:
        with RUNNING_TASKS_LOCK:
            RUNNING_TASKS.pop(execution_id, None)


def start_function_task(execution_id: int, func_name: str, **kwargs) -> None:
    runner = TASK_FUNCTIONS[func_name]
    stop_event = threading.Event()
    with RUNNING_TASKS_LOCK:
        RUNNING_TASKS[execution_id] = RunningTask(stop_event=stop_event)
    thread = threading.Thread(target=_run_task, args=(execution_id, runner), kwargs=kwargs, daemon=True)
    thread.start()


def start_command_task(execution_id: int, command: str) -> None:
    stop_event = threading.Event()
    with RUNNING_TASKS_LOCK:
        RUNNING_TASKS[execution_id] = RunningTask(stop_event=stop_event)
    thread = threading.Thread(target=_run_task, args=(execution_id, run_shell_command_task), kwargs={"command": command}, daemon=True)
    thread.start()


def stop_execution(execution_id: int) -> bool:
    with RUNNING_TASKS_LOCK:
        running = RUNNING_TASKS.get(execution_id)
    if not running:
        return False
    running.stop_event.set()
    if running.process and running.process.poll() is None:
        running.process.terminate()
    return True
