"""Device-scoped P1 telemetry; only projected metadata is stored."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, BigInteger, String, Text, UniqueConstraint, literal_column

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
    skill_audit_json = Column(Text, nullable=True)
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


class AidrEventTurn(Base):
    __tablename__ = 'aidr_event_turns'
    event_id = Column(Integer, ForeignKey('aidr_events.id', ondelete='CASCADE'), primary_key=True)
    turn_id = Column(String(256), nullable=False)


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


class AidrSkillCheck(Base):
    __tablename__ = 'aidr_skill_checks'
    __table_args__ = (Index('ix_aidr_skill_check_expiry', 'expired_at', 'received_at', 'id'),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey('aidr_devices.client_id'), index=True, nullable=False)
    usage_id = Column(Integer, ForeignKey('aidr_skill_uses.id'), index=True, nullable=False)
    payload_json = Column(Text, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expired_at = Column(DateTime, nullable=True)


class AidrSkillUse(Base):
    __tablename__ = 'aidr_skill_uses'
    __table_args__ = (UniqueConstraint('client_id', 'call_key', name='uq_aidr_skill_call'),
                     Index('ix_aidr_skill_session', 'client_id', 'agent', 'session_id', 'id'),
                     Index('ix_aidr_skill_due', 'expired_at', 'next_check_at', 'id'))
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey('aidr_devices.client_id'), nullable=False)
    call_key = Column(String(64), nullable=False)
    agent = Column(String(32), nullable=False)
    session_id = Column(String(256), nullable=False)
    behavior = Column(String(32), nullable=False)
    certification = Column(String(32), default='pending', nullable=False)
    next_check_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    payload_json = Column(Text, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expired_at = Column(DateTime, nullable=True)


for _model in (AidrEvent, AidrHookEvent, AidrCoverageRecord, AidrOperation):
    Index('ix_' + _model.__tablename__ + '_retention', _model.expired_at, _model.received_at)

RUNTIME_GOVERNANCE_INDEXES = (
    Index('ix_aidr_hook_product_arrival', AidrHookEvent.client_id,
          literal_column("json_extract(payload_json, '$.event.agent')"), AidrHookEvent.received_at,
          sqlite_where=AidrHookEvent.expired_at.is_(None)),
    Index('ix_aidr_hook_batch_latest', AidrHookBatch.client_id, AidrHookBatch.stream_id, AidrHookBatch.id),
)

HOOK_RELATED_INDEX = Index(
    'ix_aidr_hook_source_call', AidrHookEvent.client_id, AidrHookEvent.stream_id,
    literal_column("json_extract(payload_json, '$.event.native_call_id')"), AidrHookEvent.id,
    sqlite_where=AidrHookEvent.expired_at.is_(None),
)

# Session navigation reads messages separately from potentially large tool payloads.
SESSION_MESSAGE_INDEX = Index(
    'ix_aidr_session_messages', AidrEvent.client_id, AidrEvent.id, AidrEvent.agent,
    sqlite_where=AidrEvent.expired_at.is_(None) & AidrEvent.kind.in_(('user_message', 'assistant_message')),
)

# Cover session-list metadata without loading tool arguments or output bodies.
SESSION_LIST_INDEXES = (
    Index('ix_aidr_operation_device_page', AidrOperation.client_id, AidrOperation.id),
    Index('ix_aidr_hook_active_page', AidrHookEvent.client_id, AidrHookEvent.expired_at, AidrHookEvent.id),
    Index('ix_aidr_operation_product_sessions', AidrOperation.client_id, AidrOperation.expired_at,
          AidrOperation.agent, AidrOperation.id, AidrOperation.session_id, AidrOperation.latest_at),
    Index('ix_aidr_operation_session_turns', AidrOperation.client_id, AidrOperation.agent,
          AidrOperation.session_id, AidrOperation.expired_at, AidrOperation.id,
          literal_column("coalesce(json_extract(payload_json, '$.call.turn_id'), json_extract(payload_json, '$.result.turn_id'), '')"),
          literal_column("julianday(coalesce(json_extract(payload_json, '$.call.observed_at'), json_extract(payload_json, '$.result.observed_at'), latest_at))")),
    Index('ix_aidr_hook_session_turns', AidrHookEvent.client_id, AidrHookEvent.expired_at,
          *[literal_column(f"json_extract(payload_json, '$.event.{field}')") for field in ('agent', 'session_id')],
          AidrHookEvent.id,
          *[literal_column(f"json_extract(payload_json, '$.event.{field}')") for field in ('turn_id', 'kind')],
          literal_column("julianday(json_extract(payload_json, '$.received_at'))")),
    Index('ix_aidr_qoder_call_turn', AidrOperation.client_id, AidrOperation.agent, AidrOperation.session_id,
          literal_column("json_extract(payload_json,'$.call.native_call_id')"), AidrOperation.id),
    Index('ix_aidr_log_model_context', AidrEvent.client_id, AidrEvent.agent,
          literal_column("json_extract(payload_json, '$.session_id')"), AidrEvent.id,
          sqlite_where=AidrEvent.expired_at.is_(None) & (literal_column("json_type(payload_json, '$.model_context')") == 'object')),
    Index('ix_aidr_hook_session_context', AidrHookEvent.client_id,
          *[literal_column(f"json_extract(payload_json, '$.event.{field}')") for field in ('agent', 'session_id')],
          AidrHookEvent.id,
          sqlite_where=AidrHookEvent.expired_at.is_(None) & (literal_column("json_type(payload_json, '$.event.context')") == 'object')),
    Index('ix_aidr_operation_session_list', AidrOperation.client_id, AidrOperation.expired_at,
          AidrOperation.id, AidrOperation.agent, AidrOperation.session_id, AidrOperation.latest_at),
    Index('ix_aidr_hook_session_list', AidrHookEvent.client_id, AidrHookEvent.expired_at,
          *[literal_column(f"json_extract(payload_json, '$.event.{field}')") for field in ('agent', 'session_id', 'kind')],
          AidrHookEvent.id, literal_column("julianday(json_extract(payload_json, '$.received_at'))")),
    Index('ix_aidr_message_session_list', AidrEvent.client_id, AidrEvent.expired_at, AidrEvent.agent,
          literal_column("json_extract(payload_json, '$.session_id')"), AidrEvent.kind, AidrEvent.id,
          literal_column("julianday(json_extract(payload_json, '$.observed_at'))"),
          sqlite_where=AidrEvent.kind.in_(('user_message', 'assistant_message'))),
)
