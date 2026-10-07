"""Signed, device-scoped P2 snapshots. Private signing material never enters API responses."""
import base64
import json
import os
import stat
import time
from pathlib import PurePosixPath

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from .sqlite_db import Base
from .api_errors import ApiError


class AidrEnforcementRevision(Base):
    __tablename__ = 'aidr_enforcement_revisions'
    __table_args__ = (UniqueConstraint('client_id', 'revision', name='uq_aidr_enforcement_revision'),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey('managed_clients.client_id'), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    envelope_json = Column(Text, nullable=False)
    policy_json = Column(Text, nullable=False)
    created_by = Column(String(128), nullable=False)
    created_at = Column(String(32), nullable=False)


class AidrRuntimeRecord(Base):
    __tablename__ = 'aidr_runtime_records'
    __table_args__ = (UniqueConstraint('client_id', 'monitor_id', 'sequence', name='uq_aidr_runtime_record'), Index('ix_aidr_runtime_records_retention','expired_at','received_at'))
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey('managed_clients.client_id'), nullable=False, index=True)
    monitor_id = Column(String(36), nullable=False)
    sequence = Column(String(20), nullable=False)
    kind = Column(String(32), nullable=False)
    payload_json = Column(Text, nullable=False)
    received_at = Column(String(32), nullable=False)
    content_hash = Column(String(64), nullable=True)
    expired_at = Column(String(32), nullable=True)


class AidrResponseCommand(Base):
    __tablename__ = 'aidr_response_commands'
    __table_args__ = (UniqueConstraint('client_id', 'request_id', name='uq_aidr_response_request'),)
    id = Column(String(36), primary_key=True)
    client_id = Column(String(128), ForeignKey('managed_clients.client_id'), nullable=False, index=True)
    request_id = Column(String(36), nullable=False)
    envelope_json = Column(Text, nullable=False)
    target_json = Column(Text, nullable=False)
    state = Column(String(32), nullable=False, default='queued')
    created_by = Column(String(128), nullable=False)
    created_at = Column(String(32), nullable=False)
    expires_at = Column(Integer, nullable=False)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


def absolute_path(value):
    if not value.startswith('/') or value.startswith('//') or len(value) < 2 or len(value.encode()) >= 1024 or str(PurePosixPath(value)) != value or '..' in PurePosixPath(value).parts or any(ord(c) < 32 for c in value):
        raise ValueError('aidr_enforcement_path_invalid')
    return value


class Rule(Strict):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    path: str
    actor: str = Field(pattern=r'^(agent|all)$')
    decision: str = Field(pattern=r'^(allow|deny)$')
    _path = field_validator('path')(absolute_path)


class PolicyInput(Strict):
    expected_revision: str = Field(pattern=r'^(0|[1-9][0-9]{0,17})$')
    expected_configuration_revision: str | None = Field(default=None, pattern=r'^(0|[1-9][0-9]{0,17})$')
    lifetime_seconds: int = Field(default=86400, ge=60, le=30 * 86400)
    unknown_actor_action: str = Field(pattern=r'^(allow|deny)$')
    expired_action: str = Field(pattern=r'^(allow|deny)$')
    agent_executables: list[str] = Field(max_length=32)
    rules: list[Rule] = Field(max_length=128)

    @model_validator(mode='after')
    def unique(self):
        for path in self.agent_executables:
            absolute_path(path)
        if len(set(self.agent_executables)) != len(self.agent_executables) or len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError('aidr_enforcement_duplicate_selector')
        return self


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def signing_key():
    path = os.environ.get('AIDR_POLICY_SIGNING_KEY_FILE', '')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 16384 or info.st_uid != os.geteuid():
                raise ValueError('key file ownership or permissions')
            key = serialization.load_pem_private_key(source.read(16385), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError('key type')
        return key
    except (OSError, ValueError, TypeError):
        raise ApiError(503, 'aidr.enforcement_signer_unavailable', '系统防护签名密钥未就绪', 'Enforcement signing key is unavailable') from None


def sign(value):
    raw = canonical(value).encode()
    signature = signing_key().sign(raw, ec.ECDSA(hashes.SHA256()))
    return dict(payload=base64.b64encode(raw).decode(), signature=base64.b64encode(signature).decode())


def latest(db, client_id):
    return db.query(AidrEnforcementRevision).filter_by(client_id=client_id).order_by(AidrEnforcementRevision.revision.desc()).first()


def create_snapshot(client_id, body, revision):
    now = int(time.time())
    return dict(schema=1, device=client_id, revision=str(revision), issued_at=str(now), expires_at=str(now + body.lifetime_seconds),
                unknown_actor_action=body.unknown_actor_action, expired_action=body.expired_action,
                agent_executables=body.agent_executables, rules=[r.model_dump() for r in body.rules])
