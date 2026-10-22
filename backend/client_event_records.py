"""Semantic event records shared by desktop and management history APIs."""
import json
from datetime import datetime, timezone
from sqlalchemy import and_, case, cast, func, Integer, select
from .models import ClientEvent
from .aidr_models import AidrSkillUse

LEGACY_ACTIONS = {'skill_quarantined':'quarantine', 'skill_removed':'uninstall', 'skill_repaired':'restore_trusted', 'skill_quarantine_restored':'restore_quarantine', 'skill_installed':'install', 'skill_blocked':'block', 'unmanaged_skill_verified':'verify'}
CATEGORIES = ['discovery', 'audit', 'scan', 'remediation', 'installation', 'configuration', 'other']
STATES = ['alert_active', 'alert_inactive', 'recorded', 'pending', 'running', 'succeeded', 'failed', 'submitted', 'unknown']

def expressions():
    e = ClientEvent
    field = lambda name: func.json_extract(e.details_json, '$.' + name)
    action, status = field('action'), func.coalesce(field('status'), field('action_status'))
    category = case(
        (e.event_type == 'aidr_skill_alert', 'audit'),
        (e.event_type.in_(['skill_governance_recorded','skill_governance_detected','unmanaged_skill_found','unmanaged_skill_verified','skill_modified']), 'discovery'),
        (e.event_type.in_(['skill_scan_submitted','platform_scan_status']), 'scan'),
        (e.event_type.in_(['skill_governance_action','skill_quarantined','skill_removed','skill_repaired','skill_quarantine_restored','skill_blocked']), 'remediation'),
        (e.event_type.in_(['skill_installed','skill_auto_installed','skill_auto_install_failed']), 'installation'),
        (e.event_type.in_(['manual_model_credential_issued','agent_credential_issued','local_agent_binding_updated','managed_agent_auto_created','connection_changed_governance_paused','connection_changed_state_reset']), 'configuration'), else_='other')
    state = case(
        (e.event_type == 'aidr_skill_alert', case((field('active') == 1, 'alert_active'), (field('active') == 0, 'alert_inactive'), else_='unknown')),
        (or_failure(field('error_code'), status), 'failed'),
        (and_(action == 'record_only', e.event_type.in_(['skill_governance_recorded','skill_governance_detected'])), 'recorded'),
        (and_(action == 'record', e.event_type == 'skill_governance_detected'), 'recorded'),
        (e.event_type == 'skill_scan_submitted', 'submitted'),
        (status.in_(['completed','succeeded']), 'succeeded'),
        (status == 'pending', 'pending'), (status == 'running', 'running'),
        (e.event_type.in_(list(LEGACY_ACTIONS) + ['skill_auto_installed']), 'succeeded'),
        (e.event_type == 'skill_auto_install_failed', 'failed'), else_='unknown')
    evidence = func.json_each(AidrSkillUse.payload_json, '$.evidence').table_valued('value')
    evidence_time = select(func.min(func.datetime(func.json_extract(evidence.c.value, '$.at')))).select_from(evidence).correlate(AidrSkillUse).scalar_subquery()
    usage_time = select(evidence_time).where(
        AidrSkillUse.id == cast(field('usage_id'), Integer), AidrSkillUse.client_id == e.client_id,
        AidrSkillUse.expired_at.is_(None)).correlate(e).scalar_subquery()
    timestamp = case((e.event_type == 'aidr_skill_alert', func.coalesce(func.datetime(usage_time), e.created_at)), else_=func.coalesce(e.last_seen_at,e.created_at))
    return category, state, timestamp

def or_failure(error, status):
    from sqlalchemy import or_
    return or_(status == 'failed', and_(error.is_not(None), error != ''))

def present(event, details, usage=None):
    kind = event.event_type
    action = details.get('action') or LEGACY_ACTIONS.get(kind, '')
    status = details.get('status') or details.get('action_status')
    result = {'category':'other', 'title':'unknown_event', 'state':'unknown', 'action':action or 'unrecorded',
              'reason':details.get('trigger') or '', 'error':details.get('error_code') or '',
              'occurred_at':event.last_seen_at or event.created_at, 'time_kind':'occurred',
              'checked_at':None, 'path':details.get('path') or '', 'timeline':[], 'usage_id':None}
    if kind == 'aidr_skill_alert':
        check = details.get('latest_check') or details.get('certification') or {}
        behavior, stage = details.get('behavior'), details.get('stage')
        condition = (details.get('certification') or {}).get('status', 'unknown')
        title = ('audit_loaded' if behavior == 'invocation' else 'audit_read') if stage == 'host_confirmed' else ('audit_attempted' if behavior == 'invocation' else 'audit_file_attempted') if stage == 'attempted' else 'audit_check'
        observed = []
        for ref in (usage or {}).get('evidence', []):
            if ref.get('at'):
                try:
                    at = datetime.fromisoformat(ref['at'].replace('Z', '+00:00'))
                    observed.append(at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at)
                except ValueError:
                    pass
        result.update(category='audit', title=title, condition=condition, reason=details.get('reason_code') or '',
                      state='alert_active' if details.get('active') is True else 'alert_inactive' if details.get('active') is False else 'unknown',
                      action='alert', file_action='unrecorded', checked_at=check.get('checked_at'),
                      occurred_at=min(observed) if observed else event.created_at,
                      time_kind='behavior' if observed else 'recorded',
                      stage=stage or 'unknown', behavior=behavior or '', current_reason=check.get('reason') or '')
        if usage:
            result.update(usage_id=str(details['usage_id']), session_id=usage.get('session_id'),
                          path=usage.get('skill',{}).get('path',''), native_call_id=usage.get('native_call_id',''))
            result['timeline'] = [{'kind':'evidence', 'stage':ref.get('stage','unknown'), 'source':ref.get('source'),
                                   'at':ref.get('at') or ref.get('received_at'), 'arrival':not bool(ref.get('at')),
                                   'id':ref.get('id')} for ref in usage.get('evidence',[])]
    else:
        if kind == 'unmanaged_skill_verified':
            result.update(category='discovery', title='action_verify', time_kind='occurred')
        elif kind in {'skill_governance_recorded','skill_governance_detected','unmanaged_skill_found','skill_modified'}:
            result.update(category='discovery', title='discovery_' + (details.get('trigger') or ('unverified_content_changed' if kind == 'skill_modified' else 'unverified')), time_kind='discovered')
        elif kind in {'skill_governance_action', *LEGACY_ACTIONS}:
            result.update(category='installation' if action == 'install' else 'remediation', title='action_' + action)
        elif kind in {'skill_scan_submitted','platform_scan_status'}:
            result.update(category='scan', title=kind)
        elif kind in {'skill_auto_installed','skill_auto_install_failed'}:
            result.update(category='installation', title='action_install')
        elif kind in {'manual_model_credential_issued','agent_credential_issued','local_agent_binding_updated','managed_agent_auto_created','connection_changed_governance_paused','connection_changed_state_reset'}:
            result.update(category='configuration', title=kind)
        if status == 'failed' or result['error'] or kind == 'skill_auto_install_failed': result['state'] = 'failed'
        elif kind in {'skill_governance_recorded','skill_governance_detected'} and action in {'record_only','record'}: result['state'] = 'recorded'
        elif kind == 'skill_scan_submitted': result['state'] = 'submitted'
        elif status in {'pending','running'}: result['state'] = status
        elif status in {'completed','succeeded'} or kind in LEGACY_ACTIONS or kind == 'skill_auto_installed': result['state'] = 'succeeded'
    result['count_kind'] = 'discoveries' if result['category'] == 'discovery' and kind != 'unmanaged_skill_verified' else ''
    return result

def usages(db, client_id, events):
    ids = []
    for event in events:
        value = json.loads(event.details_json or '{}').get('usage_id')
        if event.event_type == 'aidr_skill_alert' and str(value).isdigit(): ids.append(int(value))
    return {row.id:{**json.loads(row.payload_json), 'session_id':row.session_id} for row in db.query(AidrSkillUse).filter(
        AidrSkillUse.client_id == client_id, AidrSkillUse.id.in_(ids), AidrSkillUse.expired_at.is_(None)).all()} if ids else {}
