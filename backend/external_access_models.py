"""External integration identities and request metadata, independent of token rotation."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, Index

from .sqlite_db import Base


class ExternalPlatform(Base):
    __tablename__ = "external_platforms"
    platform_id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    departments_json = Column(Text, default="[]", nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExternalApiRequest(Base):
    __tablename__ = "external_api_requests"
    id = Column(Integer, primary_key=True)
    request_id = Column(String(64), unique=True, index=True, nullable=False)
    client_request_id = Column(String(64), index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    platform_id = Column(String(64), index=True, nullable=True)
    platform_name = Column(String(128), nullable=True)
    token_id = Column(Integer, index=True, nullable=True)
    token_name = Column(String(128), nullable=True)
    token_prefix = Column(String(24), nullable=True)
    method = Column(String(16), nullable=False)
    route = Column(String(256), nullable=True)
    source_ip = Column(String(64), nullable=True)
    status_code = Column(Integer, index=True, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_code = Column(String(128), nullable=True)
    resource_type = Column(String(32), nullable=True)
    resource_id = Column(String(128), index=True, nullable=True)
    business_request_id = Column(String(128), index=True, nullable=True)
    department_id = Column(String(64), nullable=True)


class ExternalSkillScan(Base):
    __tablename__ = "external_skill_scans"
    task_id = Column(String(64), primary_key=True)
    trigger_source = Column(String(32), default="external_api", nullable=False)
    source_platform_id = Column(String(64), index=True, nullable=False)
    source_token_id = Column(Integer, nullable=False)
    source_request_id = Column(String(64), nullable=False)
    department_id = Column(String(64), nullable=False)
    department_group_id = Column(Integer, nullable=False)
    business_request_id = Column(String(128), index=True, nullable=False)
    external_skill_id = Column(String(128), nullable=False)
    skill_version = Column(String(128), nullable=False)
    file_sha256 = Column(String(64), nullable=False)
    version_id = Column(String(64), index=True, nullable=False)
    scan_run_id = Column(String(64), index=True, nullable=False)
    owns_scan = Column(Boolean, default=False, nullable=False)
    profile_id = Column(String(128), nullable=False)
    profile_json = Column(Text, nullable=False)
    callback_id = Column(String(128), nullable=False)
    callback_version = Column(String(128), nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    report_json = Column(Text, nullable=True)
    findings_json = Column(Text, nullable=True)
    analyzers_json = Column(Text, default="[]", nullable=False)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class ExternalResultEvent(Base):
    __tablename__ = "external_result_events"
    event_id = Column(String(64), primary_key=True)
    task_id = Column(String(64), unique=True, nullable=False)
    source_platform_id = Column(String(64), nullable=False)
    callback_id = Column(String(128), nullable=False)
    callback_version = Column(String(128), nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    last_attempt_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(64), nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_by = Column(String(128), nullable=True)


class ExternalCallbackConfig(Base):
    __tablename__ = "external_callback_configs"
    callback_id = Column(String(128), primary_key=True)
    name = Column(String(128), nullable=False)
    endpoint_id = Column(String(64), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExternalGatewayConfig(Base):
    __tablename__ = "external_gateway_configs"
    gateway_id = Column(String(128), primary_key=True)
    name = Column(String(128), nullable=False)
    endpoint_id = Column(String(64), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExternalDeliveryEndpoint(Base):
    __tablename__ = "external_delivery_endpoints"
    __table_args__ = (UniqueConstraint("kind", "config_id", "version", name="uq_external_delivery_endpoint_version"),)
    endpoint_id = Column(String(64), primary_key=True)
    kind = Column(String(16), nullable=False)
    external_gateway_id = Column(Integer, nullable=True, index=True)
    gateway_path = Column(String(2048), nullable=True)
    config_id = Column(String(128), nullable=False)
    version = Column(String(128), nullable=False)
    platform_ids_json = Column(Text, nullable=False)
    url = Column(String(2048), nullable=False)
    token_encrypted = Column(Text, nullable=False)
    timeout_seconds = Column(Integer, nullable=False)
    retry_delays_json = Column(Text, nullable=False)
    max_payload_bytes = Column(Integer, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    notification_types_json = Column(Text, default='["skill_scan", "agent_evaluation"]', nullable=False)


class ExternalDelivery(Base):
    __tablename__ = "external_deliveries"
    __table_args__ = (UniqueConstraint("kind", "task_id", name="uq_external_delivery_task"),
                     Index("ix_external_deliveries_config_created", "kind", "config_id", "created_at"))
    delivery_id = Column(String(64), primary_key=True)
    kind = Column(String(16), nullable=False)
    task_id = Column(String(64), index=True, nullable=False)
    platform_id = Column(String(64), index=True, nullable=False)
    business_request_id = Column(String(128), index=True, nullable=True)
    config_id = Column(String(128), nullable=False)
    config_version = Column(String(128), nullable=False)
    endpoint_id = Column(String(64), nullable=True)
    message_id = Column(String(128), nullable=True)
    payload_sha256 = Column(String(64), nullable=True)
    status = Column(String(32), index=True, default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    cycle_attempts = Column(Integer, default=0, nullable=False)
    lease_token = Column(String(64), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, index=True, nullable=True)
    last_error_code = Column(String(64), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    receipt_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    purpose = Column(String(16), default="result", nullable=False)
    task_type = Column(String(32), nullable=True)
    created_by = Column(String(128), nullable=True)


class ExternalDeliveryAttempt(Base):
    __tablename__ = "external_delivery_attempts"
    __table_args__ = (UniqueConstraint("delivery_id", "number", name="uq_external_delivery_attempt_number"),)
    attempt_id = Column(String(64), primary_key=True)
    delivery_id = Column(String(64), index=True, nullable=False)
    number = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    http_status = Column(Integer, nullable=True)
    error_code = Column(String(64), nullable=True)
    receipt_json = Column(Text, nullable=True)


class ExternalAgentRegistration(Base):
    __tablename__ = "external_agent_registrations"
    __table_args__ = (UniqueConstraint("platform_id", "agent_id", name="uq_external_agent_identity"),)
    registration_id = Column(String(64), primary_key=True)
    platform_id = Column(String(64), index=True, nullable=False)
    agent_id = Column(String(64), nullable=False)
    managed_agent_id = Column(String(128), unique=True, nullable=False)
    target_id = Column(String(64), nullable=False)
    credential_id = Column(String(64), nullable=False)
    department_id = Column(String(64), nullable=False)
    department_group_id = Column(Integer, nullable=False)
    registration_json = Column(Text, nullable=False)
    target_revision = Column(Integer, default=1, nullable=False)
    evaluation_sequence = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExternalAgentJob(Base):
    __tablename__ = "external_agent_jobs"
    task_id = Column(String(64), primary_key=True)
    kind = Column(String(32), nullable=False)
    registration_id = Column(String(64), index=True, nullable=False)
    platform_id = Column(String(64), index=True, nullable=False)
    department_id = Column(String(64), nullable=False)
    department_group_id = Column(Integer, nullable=False)
    agent_id = Column(String(64), nullable=False)
    target_revision = Column(Integer, nullable=False)
    credential_id = Column(String(64), nullable=False)
    registration_json = Column(Text, nullable=False)
    business_request_id = Column(String(128), index=True, nullable=True)
    profile_id = Column(String(128), nullable=True)
    profile_json = Column(Text, nullable=False)
    callback_id = Column(String(128), nullable=True)
    callback_version = Column(String(128), nullable=True)
    gateway_id = Column(String(128), nullable=True)
    gateway_version = Column(String(128), nullable=True)
    evaluation_sequence = Column(Integer, nullable=True)
    connection_test_id = Column(String(64), nullable=True)
    status = Column(String(32), default="pending", index=True, nullable=False)
    report_json = Column(Text, nullable=True)
    cases_json = Column(Text, nullable=True)
    findings_json = Column(Text, nullable=True)
    error_code = Column(String(64), nullable=True)
    checked_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class ExternalGatewayEvent(Base):
    __tablename__ = "external_gateway_events"
    task_id = Column(String(64), primary_key=True)
    gateway_id = Column(String(128), nullable=False)
    gateway_version = Column(String(128), nullable=False)
    payload_json = Column(Text, nullable=True)
    status = Column(String(32), default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    last_attempt_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(64), nullable=True)
    synced_at = Column(DateTime, nullable=True)
    receipt_id = Column(String(128), nullable=True)
    created_by = Column(String(128), nullable=True)


def upgrade_external_access_schema(engine):
    """Upgrade integration tables and indexes while preserving historical sources."""
    from sqlalchemy import inspect
    from .models import AccessToken, ManagedAgent, SecurityScanTask

    additions = {
        "external_gateway_events": {"created_by": "VARCHAR(128)"},
        "external_result_events": {"created_by": "VARCHAR(128)"},
        "external_delivery_endpoints": {"notification_types_json": "TEXT NOT NULL DEFAULT '[\"skill_scan\", \"agent_evaluation\"]'",
                                        "external_gateway_id": "INTEGER", "gateway_path": "VARCHAR(2048)"},
        "external_deliveries": {"purpose": "VARCHAR(16) NOT NULL DEFAULT 'result'", "task_type": "VARCHAR(32)", "created_by": "VARCHAR(128)"},
        "external_api_requests": {"business_request_id": "VARCHAR(128)", "client_request_id": "VARCHAR(64)"},
        "access_tokens": {"platform_id": "VARCHAR(64)", "allowed_department_ids_json": "TEXT NOT NULL DEFAULT '[]'"},
        "managed_agents": {"registration_source": "VARCHAR(32)", "source_platform_id": "VARCHAR(64)",
                           "external_agent_id": "VARCHAR(128)", "source_token_id": "INTEGER", "source_request_id": "VARCHAR(64)"},
        "security_scan_tasks": {"trigger_source": "VARCHAR(32)", "source_platform_id": "VARCHAR(64)",
                                "business_request_id": "VARCHAR(128)",
                                "external_task_id": "VARCHAR(128)", "source_token_id": "INTEGER", "source_request_id": "VARCHAR(64)"},
    }
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            # SQLite's legacy transaction mode does not begin a transaction for DDL.
            # Acquire the write lock before inspection so concurrent starts serialize.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        inspector = inspect(connection)
        for table, columns in additions.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, declaration in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}')
        for model in (AccessToken, ManagedAgent, SecurityScanTask):
            if not inspector.has_table(model.__tablename__):
                continue
            for index in sorted(model.__table__.indexes, key=lambda item: item.name):
                if any(c.name in additions[model.__tablename__] for c in index.columns):
                    index.create(connection, checkfirst=True)
        for model in (ExternalPlatform, ExternalApiRequest, ExternalSkillScan, ExternalResultEvent,
                      ExternalAgentRegistration, ExternalAgentJob, ExternalGatewayEvent,
                      ExternalDeliveryEndpoint, ExternalDelivery, ExternalDeliveryAttempt, ExternalCallbackConfig, ExternalGatewayConfig):
            model.__table__.create(connection, checkfirst=True)
            # Existing tables may come from an interrupted create_all run.
            for index in sorted(model.__table__.indexes, key=lambda item: item.name):
                index.create(connection, checkfirst=True)
        # Keep every immutable receiver version; expose the latest as the editable configuration.
        for kind, model in (("callback", ExternalCallbackConfig), ("gateway", ExternalGatewayConfig)):
            endpoints = connection.execute(ExternalDeliveryEndpoint.__table__.select().where(
                ExternalDeliveryEndpoint.kind == kind).order_by(
                    ExternalDeliveryEndpoint.created_at.desc(), ExternalDeliveryEndpoint.endpoint_id.desc())).mappings()
            known = set(connection.execute(model.__table__.select()).scalars())
            for endpoint in endpoints:
                if endpoint["config_id"] in known:
                    continue
                connection.execute(model.__table__.insert().values(**{
                    kind + "_id": endpoint["config_id"], "name": endpoint["config_id"], "endpoint_id": endpoint["endpoint_id"],
                    "enabled": endpoint["enabled"], "revision": 1, "created_by": endpoint["created_by"],
                    "created_at": endpoint["created_at"], "updated_at": endpoint["created_at"]}))
                known.add(endpoint["config_id"])
