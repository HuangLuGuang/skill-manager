"""Durable asset synchronization and versioned risk assessments."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from .sqlite_db import Base


class AssetSource(Base):
    __tablename__ = "asset_sources"
    source_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    template_target_id = Column(String(64), ForeignKey("security_targets.target_id"), nullable=False, unique=True)
    policy_id = Column(String(64), ForeignKey("security_scan_policies.policy_id"), nullable=False)
    created_by = Column(String(128), nullable=False)
    config_json = Column(Text, nullable=False)
    connection_hash = Column(String(64), nullable=False, unique=True)
    version = Column(Integer, default=1, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    next_run_at = Column(DateTime, index=True)
    active_run_id = Column(String(64))
    last_success_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AssetSyncRun(Base):
    __tablename__ = "asset_sync_runs"
    __table_args__ = (UniqueConstraint("source_id", "request_key", name="uq_asset_sync_request"),)
    run_id = Column(String(64), primary_key=True)
    source_id = Column(String(64), ForeignKey("asset_sources.source_id"), index=True, nullable=False)
    request_key = Column(String(128), nullable=False)
    config_json = Column(Text, nullable=False)
    source_version = Column(Integer, nullable=False)
    status = Column(String(32), default="pending", index=True, nullable=False)
    enumeration_complete = Column(Boolean, default=False, nullable=False)
    discovered_json = Column(Text)
    error_code = Column(String(128))
    lease_token = Column(String(64))
    lease_expires_at = Column(DateTime, index=True)
    attempt = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    cancel_requested = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime)


class SecurityAgentAsset(Base):
    __tablename__ = "security_agent_assets"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_managed_agent_source_identity"),)
    agent_id = Column(String(64), primary_key=True)
    source_id = Column(String(64), ForeignKey("asset_sources.source_id"), index=True)
    external_id = Column(String(128), nullable=False)
    display_name = Column(String(512))
    target_id = Column(String(64), ForeignKey("security_targets.target_id"), unique=True, nullable=False)
    observation_status = Column(String(32), default="observed", nullable=False)
    last_observed_at = Column(DateTime)
    snapshot_id = Column(String(64))
    config_fingerprint = Column(String(64))
    revision = Column(Integer, default=0, nullable=False)


class AssetSyncRunItem(Base):
    __tablename__ = "asset_sync_run_items"
    __table_args__ = (UniqueConstraint("run_id", "external_id", name="uq_asset_sync_run_item"),)
    item_id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("asset_sync_runs.run_id"), index=True, nullable=False)
    external_id = Column(String(128), nullable=False)
    target_id = Column(String(64), nullable=False)
    task_id = Column(String(64))
    previous_fingerprint = Column(String(64))
    status = Column(String(32), default="pending", nullable=False)
    change_kind = Column(String(32))
    error_code = Column(String(128))


class AgentScanBinding(Base):
    __tablename__ = "agent_scan_bindings"
    task_id = Column(String(64), ForeignKey("security_scan_tasks.task_id"), primary_key=True)
    agent_id = Column(String(64), ForeignKey("security_agent_assets.agent_id"), index=True, nullable=False)
    config_fingerprint = Column(String(64))
    scope_json = Column(Text, nullable=False)


class AgentRiskIssue(Base):
    __tablename__ = "agent_risk_issues"
    __table_args__ = (UniqueConstraint("agent_id", "dedup_key", name="uq_agent_risk_issue"),)
    issue_id = Column(String(64), primary_key=True)
    agent_id = Column(String(64), ForeignKey("security_agent_assets.agent_id"), index=True, nullable=False)
    dedup_key = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False)
    status = Column(String(32), default="open", nullable=False)
    finding_id = Column(String(64), nullable=False)
    evidence_json = Column(Text, default="[]", nullable=False)
    closure_task_id = Column(String(64))
    review_comment = Column(Text)
    reviewed_by = Column(String(128))
    reviewed_at = Column(DateTime)
    reviewed_config_fingerprint = Column(String(64))


class AgentAssetLink(Base):
    __tablename__ = "agent_asset_links"
    agent_id = Column(String(64), ForeignKey("security_agent_assets.agent_id"), primary_key=True)
    target_id = Column(String(64), ForeignKey("security_targets.target_id"), primary_key=True)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AgentRiskAssessment(Base):
    __tablename__ = "agent_risk_assessments"
    assessment_id = Column(String(64), primary_key=True)
    agent_id = Column(String(64), ForeignKey("security_agent_assets.agent_id"), index=True, nullable=False)
    input_hash = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)


class AssetLifecycleEvent(Base):
    __tablename__ = "asset_lifecycle_events"
    event_id = Column(String(64), primary_key=True)
    target_id = Column(String(64), index=True, nullable=False)
    task_id = Column(String(64))
    kind = Column(String(32), nullable=False)
    processed_at = Column(DateTime, index=True)
    next_attempt_at = Column(DateTime, index=True)
    error_code = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
