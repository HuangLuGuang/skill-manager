"""Batch current client issues; historical events are not device health state."""
import json
from datetime import datetime, timedelta

from sqlalchemy import func

from . import models, runtime_governance, aidr_policy
from .client_diagnostics import unresolved_incidents


def task_scope(row):
    payload = json.loads(row.payload_json or '{}')
    return row.task_type, json.dumps({k: v for k, v in payload.items()
        if k not in ('request_id', 'actor', 'task_id')}, sort_keys=True)


def unresolved_tasks(db, ids, policies, observations):
    task = models.ClientTask
    cutoff = datetime.utcnow() - timedelta(days=7)
    failed = db.query(task).filter(task.client_id.in_(ids), task.created_at >= cutoff,
                                  task.status == 'failed').all()
    if not failed:
        return {cid: [] for cid in ids}
    successes = db.query(task).filter(task.client_id.in_({row.client_id for row in failed}),
        task.task_type.in_({row.task_type for row in failed}), task.created_at >= cutoff,
        task.status == 'succeeded', task.id > min(row.id for row in failed)).all()
    rows = sorted([*failed, *successes], key=lambda row: row.id, reverse=True)
    receipts = {cid: json.loads(report.report_json) for cid, report in observations.items()}
    seen, reconciled, result = set(), set(), {cid: [] for cid in ids}
    for row in rows:
        if row.error in ('aidr_desktop_task_superseded', 'policy_superseded'):
            continue
        payload = json.loads(row.payload_json or '{}')
        key = (row.client_id, *task_scope(row))
        report = observations.get(row.client_id)
        receipt = receipts.get(row.client_id, {})
        current = policies[row.client_id]['runtime_governance_version']
        if row.status == 'succeeded' and row.task_type == 'aidr_plugin_action' and payload.get('action') == 'reconcile':
            if (payload.get('policy_version') == current == receipt.get('policy_version')
                    and receipt.get('policy_code') == 'aidr_desktop_policy_applied'
                    and datetime.utcnow() - report.reported_at < timedelta(seconds=30)):
                reconciled.add(row.client_id)
        if key in seen:
            continue
        seen.add(key)
        if row.status == 'failed' and not (row.client_id in reconciled and row.task_type == 'aidr_plugin_action'
                                          and payload.get('action') == 'reconcile'):
            result[row.client_id].append(row.id)
    return result


def batch_issues(db, clients, group):
    ids = list(group)
    observations = {r.client_id: r for r in db.query(runtime_governance.Observation).filter(runtime_governance.Observation.client_id.in_(ids))}
    devices = {r.client_id: r for r in db.query(models.AidrDevice).filter(models.AidrDevice.client_id.in_(ids))}
    audit = {r.key: json.loads(r.value) for r in db.query(models.SystemConfig).filter(
        models.SystemConfig.key.in_([aidr_policy.KEY, *(aidr_policy.CLIENT_KEY + cid for cid in ids)]))}
    policies = {cid: data['classification'] for cid, data in group.items()}
    tasks = unresolved_tasks(db, ids, policies, observations)
    runtime = unresolved_incidents(db, ids).subquery()
    runtime_counts = dict(db.query(runtime.c.client_id, func.count()).group_by(runtime.c.client_id).all())
    now = datetime.utcnow()
    for cid, data in group.items():
        issues = []
        client = clients[cid]
        report = observations.get(cid)
        receipt = json.loads(report.report_json) if report else None
        # Offline is a separate filter; stale collection reports are actionable while the client is online.
        online = client.last_seen_at and now - client.last_seen_at <= timedelta(minutes=10)
        if online and receipt:
            channels = runtime_governance.channel_view(policies[cid], receipt)
            device = devices.get(cid)
            local_audit = audit.get(aidr_policy.CLIENT_KEY + cid, {})
            effective_audit = local_audit if local_audit and not local_audit.get('inherit', True) else audit.get(aidr_policy.KEY, {})
            logs_paused = (device is not None and not device.enabled) or effective_audit.get('lifecycle', {}).get('enabled') is False
            for channel, state in channels.items():
                if channel == 'logs' and logs_paused:
                    continue
                if state['health']['severity'] == 'warning':
                    issues.append(dict(category='collection', code=state['health']['state'], channel=channel, count=1))
                elif state['target_enabled'] and not state['stale'] and state['report'] and state['report'].get('transport_code') not in (None, '', 'aidr_upload_ok', 'aidr_hook_runtime_received', 'aidr_hook_runtime_not_reported'):
                    issues.append(dict(category='collection', code='upload_failed', channel=channel, count=1))
            log_state = channels['logs']
            if device and not logs_paused and log_state['target_enabled'] and log_state['applied']:
                health = json.loads(device.health_json or '{}')
                if not device.last_seen_at or now - device.last_seen_at > timedelta(seconds=90):
                    issues.append(dict(category='collection', code='transport_offline', channel='logs', count=1))
                else:
                    reasons = {reason for source in health.get('discovery', []) for reason in source.get('reason_codes', [])
                               if reason not in ('aidr_log_discovery_pending', 'aidr_log_discovery_budget')
                               and not (reason == 'aidr_log_source_missing' and (source.get('progress') or {}).get('historical_missing')
                                        and not (source.get('progress') or {}).get('unread_missing')
                                        and not (source.get('progress') or {}).get('missing_directories'))}
                    if reasons:
                        issues.append(dict(category='collection', code='source_failed', channel='logs', count=1))
                    if health.get('upload_code') not in (None, '', 'aidr_upload_ok'):
                        issues.append(dict(category='collection', code='upload_failed', channel='logs', count=1))
        failed_skills = set()
        for skill in data['skills']:
            observation = json.loads(skill.governance_json or '{}')
            if skill.status in ('quarantine_failed', 'broken_link', 'unscannable') or (
                observation.get('signature') == skill.signature and (
                    observation.get('action_status') == 'failed' or
                    (observation.get('trigger') in ('trusted_scan_rejected', 'unverified_scan_rejected', 'malicious', 'trusted_content_changed', 'unverified_content_changed')
                     and not (observation.get('action_status') == 'completed' and observation.get('action') in ('quarantine', 'uninstall', 'restore_trusted'))))):
                failed_skills.add(skill.skill_path)
        if failed_skills:
            issues.append(dict(category='governance', code='skill_failed', count=len(failed_skills)))
        if (online and receipt and receipt.get('policy_code') not in (None, '', 'aidr_desktop_policy_applied', 'aidr_desktop_policy_applying')
                and receipt.get('policy_version') == policies[cid]['runtime_governance_version']
                and report and now - report.reported_at <= timedelta(seconds=30)):
            issues.append(dict(category='governance', code='policy_failed', count=1))
        if data['alerts']:
            issues.append(dict(category='governance', code='active_alert', count=data['alerts']))
        if tasks[cid]:
            issues.append(dict(category='tasks', code='task_failed', count=len(tasks[cid])))
        if runtime_counts.get(cid):
            issues.append(dict(category='runtime', code='runtime_failed', count=runtime_counts[cid]))
        # Several reports can describe the same channel failure.
        data['current_issues'] = list({(item['category'], item['code'], item.get('channel')): item for item in issues}.values())
        data['issue_task_ids'] = tasks[cid]
        data['issue_skill_paths'] = sorted(failed_skills)
