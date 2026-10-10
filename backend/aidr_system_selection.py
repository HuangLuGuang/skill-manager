"""Device discovery and selection; executable policy remains platform signed."""
import json
import time
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, field_validator, model_validator
from sqlalchemy import Column, ForeignKey, String, Text

from .aidr_enforcement import Strict, PolicyInput, AidrEnforcementRevision, absolute_path, canonical, create_snapshot, latest, sign
from .client_governance import policy_view
from .sqlite_db import Base
from .api_errors import ApiError


class SystemSelection(Base):
    __tablename__ = 'aidr_system_selections'
    client_id = Column(String(128), ForeignKey('managed_clients.client_id'), primary_key=True)
    inventory_json = Column(Text, nullable=False, default='[]')
    selected_json = Column(Text, nullable=False, default='[]')
    reported_at = Column(String(40), nullable=True)
    discovery_request = Column(String(36), nullable=False, default='')


class Candidate(Strict):
    id: str = Field(pattern=r'^[a-f0-9]{64}$')
    product: Literal['codex', 'claude', 'workbuddy', 'custom']
    path: str
    entry: Literal['desktop', 'bundled_cli', 'cli', 'custom']
    availability: Literal['available', 'unsigned', 'not_native', 'unreadable']
    source: Literal['common_path', 'running', 'custom']
    _path = field_validator('path')(absolute_path)


class DiscoveryInput(Strict):
    items: list[Candidate] = Field(max_length=64)
    @model_validator(mode='after')
    def unique(self):
        if len({x.id for x in self.items}) != len(self.items) or len({x.path for x in self.items}) != len(self.items):
            raise ValueError('aidr_system_duplicate_candidate')
        return self


class SelectionInput(Strict):
    expected_version: str = Field(max_length=80)
    expected_revision: str = Field(pattern=r'^(0|[1-9][0-9]{0,17})$')
    ids: list[str] = Field(min_length=1, max_length=32)


def problem(code, zh, en, status=409):
    raise ApiError(status, 'aidr.system_' + code, zh, en)


def view(db, client_id):
    policy = policy_view(db, client_id)
    target = policy['runtime_governance']
    row = db.get(SystemSelection, client_id)
    signed = latest(db, client_id)
    roots = json.loads(signed.policy_json)['agent_executables'] if signed else []
    return dict(version=policy['version'], enabled=bool(target['enabled'] and (target.get('channels') or {}).get('system')),
                runtime_enabled=target['enabled'], mode=(target.get('modes') or {}).get('system') or 'audit',
                configured=target.get('system_targets') is not None,
                requirements=target.get('system_targets') or dict(selection_mode='platform', products=[]),
                items=json.loads(row.inventory_json) if row else [],
                selected_ids=json.loads(row.selected_json) if row else [],
                reported_at=row.reported_at if row else None, discovery_request=row.discovery_request if row else '',
                revision=str(signed.revision) if signed else '0', configured_roots=roots)


def write_roots(db, client_id, paths, actor):
    current = latest(db, client_id)
    previous = json.loads(current.policy_json) if current else {}
    if previous.get('agent_executables') == paths and int(previous.get('expires_at', 0)) > time.time() + 60:
        return str(current.revision)
    body = PolicyInput(expected_revision=str(current.revision) if current else '0',
                       lifetime_seconds=86400, unknown_actor_action=previous.get('unknown_actor_action', 'allow'),
                       expired_action=previous.get('expired_action', 'allow'), agent_executables=paths,
                       rules=previous.get('rules', []))
    snapshot = create_snapshot(client_id, body, (current.revision if current else 0) + 1)
    envelope = sign(snapshot)
    db.add(AidrEnforcementRevision(client_id=client_id, revision=int(snapshot['revision']), policy_json=canonical(snapshot),
                                  envelope_json=canonical(envelope), created_by=actor, created_at=datetime.now(timezone.utc).isoformat()))
    db.flush()
    return snapshot['revision']


def select(db, client_id, body):
    state = view(db, client_id)
    if body.expected_version != state['version'] or body.expected_revision != state['revision']:
        problem('selection_conflict', '配置已更新，请重新加载后选择', 'Configuration changed; reload before selecting')
    if not state['enabled'] or not state['configured']:
        problem('collection_disabled', '平台尚未允许选择采集对象', 'Platform has not enabled target selection')
    if not state['reported_at'] or time.time() - datetime.fromisoformat(state['reported_at']).timestamp() > 300:
        problem('discovery_stale', '发现结果已过期，请重新发现', 'Discovery is stale; discover again')
    by_id = {x['id']: x for x in state['items']}
    if len(set(body.ids)) != len(body.ids) or any(i not in by_id for i in body.ids):
        problem('candidate_changed', '程序已变化，请重新发现', 'Programs changed; discover again')
    selected = [by_id[i] for i in body.ids]
    allowed = set(state['requirements']['products'])
    if any(x['availability'] != 'available' or x['product'] not in allowed for x in selected):
        problem('target_not_allowed', '所选程序不可采集或不在平台允许范围内', 'A selected program is unavailable or outside the allowed scope')
    if state['requirements']['selection_mode'] == 'platform' and {x['product'] for x in selected} != allowed:
        problem('required_product_missing', '请选择每个指定 Agent 的安装入口', 'Select an installation for every required Agent')
    revision = write_roots(db, client_id, [x['path'] for x in selected], 'device:selection')
    db.get(SystemSelection, client_id).selected_json = canonical(body.ids)
    return revision
