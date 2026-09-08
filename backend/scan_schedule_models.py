"""Recurring scan configuration and durable execution history."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from .sqlite_db import Base


class SecurityScanSchedule(Base):
    __tablename__ = "security_scan_schedules"
    schedule_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    target_id = Column(String(64), ForeignKey("security_targets.target_id"), nullable=False, index=True)
    created_by = Column(String(128), nullable=False)
    request_key = Column(String(96), nullable=False)
    __table_args__ = (UniqueConstraint("created_by", "request_key"),)
    task_json = Column(Text, nullable=False)
    timing_json = Column(Text, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    deleted_at = Column(DateTime)
    version = Column(Integer, default=1, nullable=False)
    next_run_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityScanScheduleRun(Base):
    __tablename__ = "security_scan_schedule_runs"
    run_id = Column(String(64), primary_key=True)
    schedule_id = Column(String(64), ForeignKey("security_scan_schedules.schedule_id"), nullable=False, index=True)
    request_key = Column(String(128), nullable=False)
    __table_args__ = (UniqueConstraint("schedule_id", "request_key"),)
    task_json = Column(Text, nullable=False)
    created_by = Column(String(128), nullable=False)
    trigger = Column(String(16), nullable=False)
    status = Column(String(32), default="queued", nullable=False)
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"))
    error_code = Column(String(128))
    lease_until = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityTaskRiskScore(Base):
    __tablename__ = "security_task_risk_scores"
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), primary_key=True)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SecurityTaskTrigger(Base):
    __tablename__ = "security_task_triggers"
    trigger_id = Column(String(64), primary_key=True)
    actor = Column(String(128), nullable=False)
    request_key = Column(String(128), nullable=False)
    __table_args__ = (UniqueConstraint("actor", "request_key"),)
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), nullable=False, index=True)
    kind = Column(String(32), nullable=False)
