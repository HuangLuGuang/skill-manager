"""Dify execution identities; actions and traces use the shared runtime stores."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from .sqlite_db import Base


class DifyRuntimeBinding(Base):
    __tablename__ = "dify_runtime_bindings"
    __table_args__ = (UniqueConstraint("instance_id", "workspace_id", "app_id"),)
    binding_id = Column(String(64), primary_key=True)
    target_id = Column(String(64), ForeignKey("security_targets.target_id"), nullable=True, unique=True)
    owner_user_id = Column(Integer, nullable=True)
    owner_group_id = Column(Integer, nullable=True)
    agent_id = Column(String(128), ForeignKey("managed_agents.agent_id"), nullable=False, unique=True)
    instance_id = Column(String(128), nullable=False)
    workspace_id = Column(String(128), nullable=False)
    app_id = Column(String(128), nullable=False)
    mode = Column(String(16), nullable=False, default="observe")
    revision = Column(Integer, nullable=False, default=1)
    policy_json = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DifyRuntimeSkill(Base):
    __tablename__ = "dify_runtime_skills"
    __table_args__ = (UniqueConstraint("binding_id", "dify_agent_id", "archive_hash"),)
    id = Column(Integer, primary_key=True)
    binding_id = Column(String(64), ForeignKey("dify_runtime_bindings.binding_id"), nullable=False, index=True)
    dify_agent_id = Column(String(128), nullable=False)
    archive_hash = Column(String(64), nullable=False)
    skill_name = Column(String(255), nullable=False)
    version_id = Column(String(128), nullable=False)
    seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DifyRuntimeRun(Base):
    __tablename__ = "dify_runtime_runs"
    __table_args__ = (UniqueConstraint("binding_id", "run_id"),)
    task_id = Column(String(64), ForeignKey("runtime_tasks.task_id"), primary_key=True)
    binding_id = Column(String(64), ForeignKey("dify_runtime_bindings.binding_id"), nullable=False, index=True)
    run_id = Column(String(128), nullable=False)
    workflow_id = Column(String(128), nullable=False)
    graph_digest = Column(String(64), nullable=False)


class DifyRuntimeCall(Base):
    __tablename__ = "dify_runtime_calls"
    __table_args__ = (UniqueConstraint("task_id", "call_id"),)
    action_id = Column(String(64), ForeignKey("runtime_actions.action_id"), primary_key=True)
    task_id = Column(String(64), ForeignKey("runtime_tasks.task_id"), nullable=False, index=True)
    call_id = Column(String(128), nullable=False)
    node_id = Column(String(128), nullable=False)
    execution_id = Column(String(128), nullable=False)
    revision = Column(Integer, nullable=False)
    context_json = Column(Text, nullable=False)
    approval_status = Column(String(24), nullable=False, default="none")
    approval_deadline = Column(DateTime, nullable=True)


class DifyRuntimeProcess(Base):
    __tablename__ = "dify_runtime_processes"
    __table_args__ = (UniqueConstraint("binding_id", "process_id"),)
    id = Column(Integer, primary_key=True)
    binding_id = Column(String(64), ForeignKey("dify_runtime_bindings.binding_id"), nullable=False, index=True)
    process_id = Column(String(128), nullable=False)
    report_json = Column(Text, nullable=False)
    seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
