"""Read-only Hook onboarding evidence; configuration is never an execution receipt."""
import json
from datetime import datetime, timedelta, timezone

from . import models, aidr_policy
from .aidr_models import AidrHookBatch, AidrHookEvent
from .aidr_hook_runtime import HookRuntimeRow

RECENT_SECONDS = 15 * 60
# The daemon inspects every five minutes; each of the two hosts may take a minute.
HOST_OBSERVATION_SECONDS = 8 * 60


def parsed_time(value):
    try:
        at = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return at.astimezone(timezone.utc).replace(tzinfo=None) if at.tzinfo else at
    except (TypeError, ValueError, AttributeError):
        return None


def fresh(value, now, seconds):
    at = parsed_time(value)
    return bool(at and now-timedelta(seconds=seconds) <= at <= now+timedelta(seconds=5))


def step(key, status, action, evidence=None):
    return {'key': key, 'status': status, 'next_action': action, 'evidence': evidence or {}}


def view(db, client_id, policy, report, stale, compatibility):
    now = datetime.utcnow()
    target = policy['runtime_governance']
    configured = policy['runtime_governance_configured']
    explicit = target.get('channels')
    required = None if not configured else bool(target['enabled'] and (explicit is None or explicit['hooks']))
    policy_row = db.get(models.ClientGovernancePolicy, client_id if policy['runtime_governance_source'] == 'client' else '@default')
    cutoff = max(now-timedelta(seconds=RECENT_SECONDS), policy_row.updated_at if policy_row else now-timedelta(seconds=RECENT_SECONDS))
    config = step('configuration', 'confirmed' if configured else 'unknown', 'configure_policy',
                  {'type': 'platform_policy', 'version': policy['runtime_governance_version'],
                   'source': policy['runtime_governance_source'], 'at': policy_row.updated_at.isoformat()+'Z' if policy_row else None,
                   'target_enabled': required})
    audit_enabled = aidr_policy.current(db, client_id).get('lifecycle', {}).get('enabled', True)
    hosts = []
    if required and audit_enabled:
        events = db.query(AidrHookEvent).filter(AidrHookEvent.client_id == client_id, AidrHookEvent.expired_at.is_(None), AidrHookEvent.received_at >= cutoff).order_by(AidrHookEvent.id.desc()).limit(100).all()
        receivers = db.query(HookRuntimeRow).filter(HookRuntimeRow.client_id == client_id, HookRuntimeRow.received_at >= int((now-timedelta(seconds=90)).replace(tzinfo=timezone.utc).timestamp())).all()
    else:
        events, receivers = [], []
    for agent in target['hosts']:
        items = [config.copy()]
        host = next((item for item in (report or {}).get('hosts', []) if item['agent'] == agent), None)
        host_fresh = bool(host and not stale and fresh(host.get('reported_at'), now, HOST_OBSERVATION_SECONDS))
        host_evidence = {'type': 'native_host_client_report', 'at': host.get('reported_at') if host else None,
                         'installed': host.get('installed') if host else None, 'enabled': host.get('enabled') if host else None,
                         'trust': host.get('hook_trust') if host else None}
        items.append(step('capabilities', 'reported' if compatibility['state'] == 'reported_current' else 'attention' if compatibility['state'] in ('legacy', 'partial') else 'unknown', 'upgrade_client',
                          {'type': compatibility['evidence_type'], 'at': compatibility.get('reported_at'), 'protocol': compatibility['protocol'], 'current': compatibility['current']}))
        items.append(step('installation', 'reported' if host_fresh and host.get('installed') is True else 'attention' if host_fresh and host.get('installed') is False else 'unknown', 'inspect_host', host_evidence))
        trusted = bool(host_fresh and host.get('enabled') is True and host.get('hook_trust') in ('trusted', 'managed'))
        items.append(step('native_trust', 'reported' if trusted else 'attention' if host_fresh and (host.get('enabled') is False or host.get('hook_trust') == 'needs_review') else 'unknown', 'enable_and_trust', host_evidence))
        # No current native-loading report proves a new host process loaded hooks.
        items.append(step('host_loading', 'unknown', 'new_host_session', {'type': 'no_host_loading_receipt'}))
        receiver_evidence = {'type': 'receiver_client_report', 'at': (((report or {}).get('channels') or {}).get('hooks') or {}).get('reported_at'),
                             'code': (report or {}).get('receiver_code'), 'policy_version': (report or {}).get('policy_version')}
        running = bool(not stale and report and report.get('policy_version') == policy['runtime_governance_version'] and report.get('receiver_code') == 'aidr_desktop_running' and fresh(receiver_evidence['at'], now, 30))
        items.append(step('receiver', 'reported' if running else 'unknown', 'inspect_receiver', receiver_evidence))
        event = next((row for row in events if json.loads(row.payload_json).get('event', {}).get('agent') == agent), None)
        record = json.loads(event.payload_json) if event else {}
        event_evidence = {'type': 'platform_event', 'id': str(event.id), 'at': event.received_at.isoformat()+'Z', 'stream_id': event.stream_id} if event else {}
        items.append(step('event_arrival', 'confirmed' if event else 'unknown', 'generate_event', event_evidence))
        receipt = db.query(AidrHookBatch).filter_by(client_id=client_id, stream_id=event.stream_id).filter(AidrHookBatch.received_at >= cutoff).order_by(AidrHookBatch.id.desc()).first() if event else None
        receipt_evidence = {'type': 'platform_durable_batch', 'id': str(receipt.id), 'at': receipt.received_at.isoformat()+'Z', 'digest': receipt.digest, 'stream_id': receipt.stream_id} if receipt else {}
        items.append(step('platform_receipt', 'confirmed' if receipt else 'unknown', 'inspect_upload', receipt_evidence))
        ack = next((row for row in receivers if event and receipt and record.get('receiver_instance') == row.receiver_instance and row.stream_id == event.stream_id and
                    (parsed_time(json.loads(row.payload).get('last_event_ack_at')) or datetime.min) >= event.received_at and
                    (parsed_time(json.loads(row.payload).get('last_event_ack_at')) or datetime.max) <= now+timedelta(seconds=5)), None)
        ack_evidence = {'type': 'client_ack_report', 'at': json.loads(ack.payload).get('last_event_ack_at'),
                        'stream_id': ack.stream_id, 'receiver_instance': ack.receiver_instance,
                        'report_received_at': str(ack.received_at)} if ack else {}
        items.append(step('client_ack', 'reported' if ack else 'unknown', 'inspect_upload', ack_evidence))
        if not audit_enabled:
            items = [step(item['key'], 'not_required', 'configure_policy') if item['key'] in ('event_arrival', 'platform_receipt', 'client_ack') else item for item in items]
        if required is False:
            items = [items[0]] + [step(item['key'], 'not_required', 'configure_policy') for item in items[1:]]
        elif required is None:
            items = [step(item['key'], 'unknown', 'configure_policy', item['evidence']) for item in items]
        blocking = next((item for item in items if item['key'] != 'host_loading' and item['status'] in ('unknown', 'attention')), None)
        loading = next(item for item in items if item['key'] == 'host_loading')
        if event and required and loading['status'] == 'unknown':
            loading['evidence']['hook_event_observed_at'] = event.received_at.isoformat()+'Z'
        hosts.append({'agent': agent, 'steps': items, 'next_step': blocking})
    return {'scope': 'hook_plugin_onboarding', 'target_enabled': required, 'audit_enabled': audit_enabled,
            'recent_window_seconds': RECENT_SECONDS, 'evidence_after': cutoff.isoformat()+'Z', 'checked_at': now.isoformat()+'Z',
            'truncated_events': len(events) == 100, 'hosts': hosts}
