"""Global tool rules, explicit device overrides and lazy device-scoped signing."""
import json
import time

from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, select, func, literal
from sqlalchemy.dialects.sqlite import insert
from pydantic import Field

from .sqlite_db import Base
from . import aidr_hook_control as control
from .aidr_enforcement import canonical


class ToolPolicyConfig(Base):
    __tablename__ = 'aidr_tool_policy_configs'
    __table_args__ = (UniqueConstraint('scope', 'revision'),)
    id = Column(Integer, primary_key=True)
    scope = Column(String(140), nullable=False)
    revision = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False)
    author = Column(String(128), nullable=False)
    created_at = Column(Integer, nullable=False)


class ToolPolicyDelivery(Base):
    __tablename__ = 'aidr_tool_policy_deliveries'
    client_id = Column(String(128), primary_key=True)
    global_revision = Column(Integer, nullable=False)
    device_revision = Column(Integer, nullable=False)


class ClientPolicyInput(control.ToolPolicyInput):
    inherit: bool = False
    expected_global_revision: str | None = Field(default=None, pattern=r'^(0|[1-9][0-9]{0,17})$')
    expected_scope_revision: str | None = Field(default=None, pattern=r'^(0|[1-9][0-9]{0,17})$')


def config(db, scope):
    return db.query(ToolPolicyConfig).filter_by(scope=scope).order_by(ToolPolicyConfig.revision.desc()).first()


def initialize_global_policy(db):
    """Seed the published baseline atomically; the caller owns the transaction."""
    values = select(literal('global'), literal(1),
        literal(canonical({'default_action': 'allow', 'rules': []})),
        literal('system'), literal(int(time.time()))).where(
            ~select(ToolPolicyConfig.id).where(ToolPolicyConfig.scope == 'global').exists())
    db.execute(insert(ToolPolicyConfig).from_select(
        ['scope', 'revision', 'payload', 'author', 'created_at'], values).on_conflict_do_nothing())


def inherits(db, client_id):
    row = config(db, 'client:' + client_id)
    return json.loads(row.payload)['inherit'] if row else control.latest_policy(db, client_id) is None


def global_view(db):
    row = config(db, 'global')
    return {'revision': str(row.revision) if row else '0',
            'policy': json.loads(row.payload) if row else None,
            'analysis': {'published_by': row.author, 'issued_at': str(row.created_at)} if row else None}


def scope_view(db, client_id):
    global_policy = global_view(db)
    inherit = inherits(db, client_id)
    delivery = db.get(ToolPolicyDelivery, client_id)
    target = int(global_policy['revision'])
    pending = inherit and target > 0 and (delivery is None or delivery.global_revision != target)
    local = config(db, 'client:' + client_id)
    return {'inherit': inherit, 'scope_revision': str(local.revision if local else 0), 'global_revision': str(target), 'global_policy': global_policy['policy'],
            'distribution': 'pending' if pending else 'issued' if inherit and target else 'local' if not inherit else 'unconfigured'}


def append_config(db, scope, revision, payload, author):
    result = db.execute(insert(ToolPolicyConfig).values(scope=scope, revision=revision,
        payload=canonical(payload), author=author, created_at=int(time.time())).on_conflict_do_nothing())
    if not result.rowcount:
        control.reject('hook_policy_conflict', '工具策略版本已变化，请刷新', 'Tool policy revision changed; refresh')


def impact(db):
    # One set-based count, without loading each device or its event history.
    from .models import ManagedClient
    latest = select(ToolPolicyConfig.scope, func.max(ToolPolicyConfig.revision).label('rev')).where(
        ToolPolicyConfig.scope != 'global').group_by(ToolPolicyConfig.scope).subquery()
    overrides = select(ToolPolicyConfig.scope).join(latest,
        (ToolPolicyConfig.scope == latest.c.scope) & (ToolPolicyConfig.revision == latest.c.rev)).where(
        func.json_extract(ToolPolicyConfig.payload, '$.inherit') == 0)
    explicit = select(latest.c.scope)
    legacy = select(control.HookPolicyRow.client_id).distinct()
    inherited = db.query(ManagedClient).filter(
        ~('client:' + ManagedClient.client_id).in_(overrides),
        (~ManagedClient.client_id.in_(legacy)) | ('client:' + ManagedClient.client_id).in_(explicit)).count()
    total = db.query(ManagedClient).count()
    return {'inherited': inherited, 'overridden': total - inherited}


def publish_global(db, body, author):
    current = global_view(db)
    if body.expected_revision != current['revision']:
        control.reject('hook_policy_conflict', '全局策略已变化，请刷新', 'Global policy changed; refresh')
    payload = {'default_action': body.default_action, 'approval_wait_seconds': body.approval_wait_seconds, 'rules': [r.model_dump(exclude_none=True) for r in body.rules]}
    # Leave room for the device envelope, including the largest device ID.
    if len(canonical(payload).encode()) > 23000:
        control.reject('hook_policy_too_large', '工具策略超过大小限制', 'Tool policy exceeds the size limit', 422)
    append_config(db, 'global', int(current['revision']) + 1, payload, author)
    return global_view(db)


def publish_client(db, client_id, body, author):
    previous = config(db, 'client:' + client_id)
    if ((body.expected_scope_revision is not None and body.expected_scope_revision != str(previous.revision if previous else 0))
            or (body.expected_scope_revision is None and previous is not None and json.loads(previous.payload)['inherit'])):
        control.reject('hook_policy_conflict', '规则来源已变化，请刷新', 'Rule source changed; refresh')
    row = control.latest_policy(db, client_id)
    if body.expected_revision != str(row.revision if row else 0):
        control.reject('hook_policy_conflict', '工具策略版本已变化，请刷新', 'Tool policy revision changed; refresh')
    if body.inherit:
        global_policy = global_view(db)
        if body.expected_global_revision != global_policy['revision']:
            control.reject('hook_policy_conflict', '全局策略已变化，请刷新', 'Global policy changed; refresh')
        if global_policy['policy'] is None:
            control.reject('hook_global_missing', '请先发布全局规则', 'Publish global rules first')
    else:
        control.publish(db, client_id, body, author)
    append_config(db, 'client:' + client_id, (previous.revision if previous else 0) + 1, {'inherit': body.inherit}, author)
    # A return to inheritance must issue even when its global revision did not change.
    db.query(ToolPolicyDelivery).filter_by(client_id=client_id).delete()


def reconcile(db, client_id):
    if not inherits(db, client_id):
        return
    source = config(db, 'global')
    if source is None:
        return
    delivery = db.get(ToolPolicyDelivery, client_id)
    if delivery is not None and delivery.global_revision == source.revision:
        return
    previous = control.latest_policy(db, client_id)
    body = control.ToolPolicyInput(expected_revision=str(previous.revision if previous else 0), **json.loads(source.payload))
    policy = control.publish(db, client_id, body, source.author)
    # Persist the default inherited choice before a generated policy can look like a legacy override.
    if config(db, 'client:' + client_id) is None:
        append_config(db, 'client:' + client_id, 1, {'inherit': True}, source.author)
    db.execute(insert(ToolPolicyDelivery).values(client_id=client_id, global_revision=source.revision,
        device_revision=int(policy['revision'])).on_conflict_do_update(index_elements=['client_id'],
        set_={'global_revision': source.revision, 'device_revision': int(policy['revision'])}))


def require_current(db, client_id):
    if scope_view(db, client_id)['distribution'] == 'pending':
        control.reject('hook_policy_conflict', '新全局规则待同步，请等待客户端获取', 'New global rules await client synchronization')
