"""Device-scoped P1 telemetry; only projected metadata is stored."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, BigInteger, String, Text, UniqueConstraint

from .sqlite_db import Base


class AidrPolicyReceipt(Base):
    __tablename__ = "aidr_policy_receipts"
    id = Column(String(32), primary_key=True)
    client_id = Column(String(128), ForeignKey("aidr_devices.client_id"), nullable=False, index=True)
    stream_id = Column(String(32), nullable=False)
    version = Column(String(20), nullable=False)
    enabled = Column(Boolean, nullable=False)
    capture_json = Column(Text, nullable=True)
    lifecycle_json = Column(Text, nullable=True)
    start_sequence = Column(BigInteger, nullable=False)
    end_sequence = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AidrDevice(Base):
    __tablename__ = "aidr_devices"
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), primary_key=True)
    enabled = Column(Boolean, default=True, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    health_json = Column(Text, default="{}", nullable=False)
    capabilities_json = Column(Text, default="[]", nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AidrHookBatch(Base):
    __tablename__ = "aidr_hook_batches"
    __table_args__ = (UniqueConstraint("client_id", "stream_id", "digest", name="uq_aidr_hook_batch"),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("aidr_devices.client_id"), nullable=False)
    stream_id = Column(String(32), nullable=False)
    digest = Column(String(64), nullable=False)
    record_count = Column(Integer, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AidrHookEvent(Base):
    __tablename__ = "aidr_hook_events"
    __table_args__ = (
        UniqueConstraint("client_id", "stream_id", "event_id", name="uq_aidr_hook_event"),
        UniqueConstraint("client_id", "stream_id", "source_seq", name="uq_aidr_hook_sequence"),
        Index("ix_aidr_hook_page", "client_id", "id"),
    )
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("aidr_devices.client_id"), nullable=False)
    stream_id = Column(String(32), nullable=False)
    event_id = Column(String(32), nullable=False)
    source_seq = Column(BigInteger, nullable=False)
    content_hash = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expired_at = Column(DateTime, nullable=True)


class AidrBatch(Base):
    __tablename__ = "aidr_batches"
    __table_args__ = (UniqueConstraint("client_id", "stream_id", "batch_id", name="uq_aidr_batch"),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("aidr_devices.client_id"), nullable=False, index=True)
    stream_id = Column(String(32), nullable=False)
    batch_id = Column(String(64), nullable=False)
    digest = Column(String(64), nullable=False)
    record_count = Column(Integer, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AidrEvent(Base):
    __tablename__ = "aidr_events"
    __table_args__ = (
        UniqueConstraint("client_id", "logical_id", name="uq_aidr_logical_event"),
        Index("ix_aidr_event_device_page", "client_id", "id"),
    )
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("aidr_devices.client_id"), nullable=False)
    logical_id = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    agent = Column(String(16), nullable=False)
    kind = Column(String(32), nullable=False)
    payload_json = Column(Text, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expired_at = Column(DateTime, nullable=True)


class AidrSource(Base):
    __tablename__ = "aidr_sources"
    __table_args__ = (UniqueConstraint("client_id", "stream_id", "source_id", name="uq_aidr_source"),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("aidr_devices.client_id"), nullable=False, index=True)
    stream_id = Column(String(32), nullable=False)
    source_id = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False)
    payload_json = Column(Text, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AidrCoverageRecord(Base):
    __tablename__ = "aidr_coverage_records"
    __table_args__ = (UniqueConstraint("client_id", "stream_id", "record_id", name="uq_aidr_coverage_record"),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("aidr_devices.client_id"), nullable=False, index=True)
    stream_id = Column(String(32), nullable=False)
    record_id = Column(String(85), nullable=False)
    payload_json = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expired_at = Column(DateTime, nullable=True)


class AidrLegacyDestination(Base):
    """Historical suffix needed to verify existing hashed local destinations."""
    __tablename__ = "aidr_legacy_destinations"
    client_id = Column(String(128), primary_key=True)
    suffix = Column(String(32), nullable=False)


class AidrOperation(Base):
    __tablename__ = 'aidr_operations'
    __table_args__ = (UniqueConstraint('client_id','operation_key',name='uq_aidr_operation'), Index('ix_aidr_operation_recent','client_id','latest_at','id'))
    id = Column(Integer,primary_key=True)
    client_id = Column(String(128),ForeignKey('aidr_devices.client_id'),nullable=False)
    operation_key = Column(String(64),nullable=False)
    agent = Column(String(16),nullable=False)
    session_id = Column(String(256),nullable=False)
    tool = Column(String(256),nullable=False)
    result_status = Column(String(32),nullable=False)
    latest_at = Column(String(40),nullable=False)
    payload_json = Column(Text,nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expired_at = Column(DateTime, nullable=True)


class AidrAuditState(Base):
    __tablename__ = 'aidr_audit_state'
    key = Column(String(64),primary_key=True)
    value = Column(Integer,nullable=False)


for _model in (AidrEvent, AidrHookEvent, AidrCoverageRecord, AidrOperation):
    Index('ix_' + _model.__tablename__ + '_retention', _model.expired_at, _model.received_at)
