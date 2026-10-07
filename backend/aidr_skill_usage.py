"""Skill evidence and fresh registry checks; never participates in tool decisions."""
import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert
from starlette.concurrency import run_in_threadpool

from . import aidr_policy, models
from .aidr_models import AidrAuditState, AidrEvent, AidrHookEvent, AidrSkillUse
from agent_manager.core.signer import compute_content_digest, verify_signature, signature_content_digest, verify_content_digest


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def identity(client_id, event, source, record_id):
    # Entry identities stay distinct: shared Qoder Hooks do not identify CLI/IDE.
    parts = [client_id, event.get('user_scope') or ('unscoped:' + source), event.get('agent'), event.get('session_id'), event.get('native_agent_id', ''), event.get('native_call_id')]
    if event.get('agent') == 'codex':
        # Codex call identity is scoped to its native turn in the log contract.
        parts.append(event.get('turn_id') or ('unscoped:' + source))
    if not event.get('native_call_id') or not event.get('session_id'):
        parts += [source, str(record_id)]
    return hashlib.sha256(dump(parts).encode()).hexdigest()


def stage(event):
    if event.get('kind') in {'tool.failure', 'permission.denied'}:
        return 'failed'
    status = (event.get('behavior') or {}).get('status')
    if status in {'reported_error', 'reported_cancelled'} or event.get('outcome') == 'error':
        return 'failed'
    if event.get('kind') in {'tool.post', 'tool_result'}:
        if (event.get('skill_use') or {}).get('phase') == 'host_loaded':
            return 'host_confirmed'
        if status in {'reported_success', 'reported_complete'} or event.get('outcome') == 'success':
            return 'host_confirmed'
        return 'unknown'
    return 'attempted'


def merge(db, source, record):
    raw = json.loads(record.payload_json)
    event = {**raw.get('event', {}), 'user_scope':raw.get('user_scope')} if source == 'hook' else raw
    key = identity(record.client_id, event, source, record.id)
    row = db.query(AidrSkillUse).filter_by(client_id=record.client_id, call_key=key).first()
    skill = event.get('skill_use')
    if row is None and not skill:
        return
    if row and row.expired_at:
        return
    data = json.loads(row.payload_json) if row else {
        'skill': skill, 'stage': 'attempted', 'evidence': [], 'identity_ambiguous': False,
        'native_call_id': event.get('native_call_id', ''), 'native_agent_id': event.get('native_agent_id', ''),
        'entry': event.get('agent'), 'agent_version': event.get('agent_version') or None,
        'tool': event.get('tool'), 'user_scope': event.get('user_scope'),
        'first_at': event.get('observed_at') or raw.get('received_at') or record.received_at.isoformat() + 'Z',
    }
    ref = {'source': source, 'id': str(record.id), 'kind': event.get('kind'), 'stage': stage(event)}
    if ref in data['evidence']:
        return
    if data.get('tool') and event.get('tool') and data['tool'] != event['tool']:
        data['identity_ambiguous'] = True
    if skill:
        old = data['skill']
        if any(old.get(k) and skill.get(k) and old[k] != skill[k] for k in ('name', 'path', 'behavior', 'content_digest')):
            data['identity_ambiguous'] = True
        else:
            data['skill'] = {**old, **{k:v for k,v in skill.items() if v}}
    if len(data['evidence']) < 64:
        data['evidence'].append(ref)
    else:
        data['identity_ambiguous'] = True
    results = {r['stage'] for r in data['evidence'] if r['kind'] in {'tool.post','tool_result','tool.failure'}}
    data['stage'] = ('unknown' if {'host_confirmed','failed'} <= results else
                     'failed' if 'failed' in results else 'host_confirmed' if 'host_confirmed' in results else
                     'unknown' if results else 'attempted')
    if row is None:
        row = AidrSkillUse(client_id=record.client_id, call_key=key, agent=event['agent'], session_id=event.get('session_id',''),
                          behavior=skill['behavior'], payload_json=dump(data), received_at=record.received_at)
        db.add(row)
        db.flush()
        # Out-of-order uploads: join only exact native identity, within the same
        # entry/session. No timestamp or name-based association is performed.
        if event.get('native_call_id') and event.get('session_id'):
            for model, kind, prefix in ((AidrEvent,'log','$.'),(AidrHookEvent,'hook','$.event.')):
                q = db.query(model).filter(model.client_id == record.client_id, model.expired_at.is_(None))
                for field in ('agent','session_id','native_call_id'):
                    q = q.filter(func.json_extract(model.payload_json, prefix + field) == event[field])
                for related in q.order_by(model.id).limit(65):
                    if kind == source and related.id == record.id:
                        continue
                    other = json.loads(related.payload_json)
                    other = {**other.get('event',{}), 'user_scope':other.get('user_scope')} if kind == 'hook' else other
                    if identity(record.client_id, other, kind, related.id) == key:
                        r = {'source':kind,'id':str(related.id),'kind':other.get('kind'),'stage':stage(other)}
                        if r not in data['evidence'] and len(data['evidence']) < 64:
                            data['evidence'].append(r)
            results = {r['stage'] for r in data['evidence'] if r['kind'] in {'tool.post','tool_result','tool.failure'}}
            data['stage'] = 'unknown' if {'host_confirmed','failed'} <= results else 'failed' if 'failed' in results else 'host_confirmed' if 'host_confirmed' in results else 'unknown' if results else 'attempted'
    row.payload_json = dump(data)


def certification(db, row, manager):
    data = json.loads(row.payload_json)
    skill = data['skill']
    result = {'status':'pending','reason':'source_unknown','registered':None,'approved':None,'revoked':None,
              'content_matches':None,'authorized':None,'managed_agent_id':None,'local_agent_id':None,
              'checked_at':datetime.utcnow().isoformat()+'Z', 'basis':'post_collection_content_observation'}
    if data['identity_ambiguous']:
        return {**result, 'reason':'identity_ambiguous'}
    if not skill.get('path') or not skill.get('content_digest'):
        return result
    root = str(PurePosixPath(skill['path']).parent)
    installations = db.query(models.ClientSkillInstall).filter_by(client_id=row.client_id, skill_path=root).all()
    ids = {item.version_id or item.skill_id for item in installations if item.version_id or item.skill_id}
    if manager is None:
        raise RuntimeError('registry_unavailable')
    entries = manager.list_skills()
    if len(ids) > 1:
        return {**result,'reason':'identity_ambiguous'}
    expected_id = next(iter(ids), None)
    entry = next((e for e in entries if e.skill_id == expected_id), None) if expected_id else None
    if expected_id and entry is None:
        return {**result, 'reason':'registry_reference_missing'}
    digests = {}
    # No name fallback. A known installed version or exact content identifies
    # a registry entry; multiple registrations of identical content stay unknown.
    candidates = [entry] if entry else [e for e in entries if not skill.get('name') or e.name == skill['name']]
    unavailable = False
    for candidate in candidates:
        digest = signature_content_digest(candidate.signature)
        try:
            digests[candidate.skill_id] = digest or compute_content_digest(candidate.skill_path)
        except (OSError, ValueError, TypeError):
            unavailable = True
    if not entry:
        matches = [e for e in candidates if digests.get(e.skill_id) == skill['content_digest']]
        if unavailable:
            return {**result,'reason':'registry_content_unavailable'}
        if len(matches) > 1:
            return {**result,'reason':'identity_ambiguous'}
        if not matches:
            return {**result,'registered':False,'status':'unregistered','reason':'unregistered'}
        entry = matches[0]
    state = getattr(entry.status,'value',entry.status)
    result.update(registered=True, approved=state in {'APPROVED','DEPLOYED'}, revoked=state == 'RETIRED',
                  content_matches=digests.get(entry.skill_id) == skill['content_digest'], skill_id=entry.skill_id,
                  name=entry.name, version_no=getattr(entry,'version_no',None), expected_digest=digests.get(entry.skill_id))
    if not result['expected_digest']:
        return {**result,'reason':'registry_content_unavailable'}
    if not result['content_matches']:
        return {**result,'status':'content_changed','reason':'content_changed'}
    if result['revoked']:
        return {**result,'status':'revoked','reason':'revoked'}
    if not result['approved']:
        return {**result,'status':'unapproved','reason':'unapproved'}
    signed_digest = signature_content_digest(entry.signature)
    verified = verify_content_digest(skill['content_digest'], entry.signature) if signed_digest else bool(entry.signature and verify_signature(entry.skill_path, entry.signature))
    if not verified:
        return {**result,'reason':'signature_unverified'}
    # Inventory ownership is usable only for a unique product instance whose
    # configured Skill root contains this exact observed source.
    types = {'claude':'claude-code','codex':'codex','workbuddy':'workbuddy','qoder-cli':'qoder','qoder-work':'qoderwork','cursor':'cursor','opencode':'opencode'}
    agents = db.query(models.ClientAgent).filter_by(client_id=row.client_id, agent_type=types.get(row.agent,'')).all()
    agents = [a for a in agents if a.skills_path and PurePosixPath(root).is_relative_to(PurePosixPath(a.skills_path)) and a.local_agent_id]
    if len(agents) != 1 or not agents[0].managed_agent_id or data.get('native_agent_id'):
        return {**result,'reason':'agent_identity_unknown','status':'verified_content'}
    local = agents[0]
    managed = db.query(models.ManagedAgent).filter_by(agent_id=local.managed_agent_id).first()
    if not managed:
        return {**result,'reason':'agent_identity_unknown','status':'verified_content'}
    refs = set(json.loads(managed.skill_names_json))
    allowed = managed.status == 'active' and bool(refs & {entry.skill_id,entry.name,getattr(entry,'family_id',None)})
    return {**result,'authorized':allowed,'local_agent_id':local.local_agent_id,'managed_agent_id':managed.agent_id,
            'status':'verified' if allowed else 'unauthorized','reason':'verified' if allowed else 'unauthorized',
            'identity_basis':'unique_inventory_skill_root'}


def refresh(db, row, manager):
    original = row.payload_json
    data = json.loads(row.payload_json)
    settings = aidr_policy.current(db,row.client_id).get('skill_audit', {'enabled':True,'alerts':True})
    try:
        check = certification(db, row, manager) if settings['enabled'] else {'status':'pending','reason':'audit_disabled','checked_at':datetime.utcnow().isoformat()+'Z'}
    except (OSError, ValueError, RuntimeError):
        check = {'status':'pending','reason':'query_failed','checked_at':datetime.utcnow().isoformat()+'Z'}
    data['certification'] = check
    # A concurrent ingest must not lose new evidence to an older check snapshot.
    changed = db.query(AidrSkillUse).filter_by(id=row.id, payload_json=original).update(
        {'certification':check['status'], 'payload_json':dump(data)}, synchronize_session=False)
    db.expire(row)
    if not changed:
        return {'id':str(row.id),'agent':row.agent,'session_id':row.session_id,**json.loads(row.payload_json)}
    settings = aidr_policy.current(db,row.client_id).get('skill_audit', {'enabled':True,'alerts':True})
    bad = {'unregistered','unapproved','revoked','content_changed','unauthorized'}
    key = hashlib.sha256(('skill-use:' + row.client_id + ':' + row.call_key).encode()).hexdigest()
    if settings['enabled'] and settings['alerts'] and check['status'] in bad:
        details = {'active':True,'usage_id':str(row.id),'behavior':row.behavior,'stage':data['stage'],'reason_code':check['reason'],
                   'certification':check,'evidence':data['evidence']}
        key = hashlib.sha256(('skill-use:' + row.client_id + ':' + row.call_key).encode()).hexdigest()
        values = dict(client_id=row.client_id,event_type='aidr_skill_alert',agent_type=row.agent,
                      skill_name=data['skill'].get('name') or check.get('name'),details_json=dump(details),
                      aggregate_key=key,last_seen_at=datetime.utcnow())
        stmt = insert(models.ClientEvent).values(**values)
        db.execute(stmt.on_conflict_do_update(index_elements=['aggregate_key'],set_={k:v for k,v in values.items() if k != 'aggregate_key'}))
    else:
        previous = db.query(models.ClientEvent).filter_by(aggregate_key=key).first()
        if previous:
            details = json.loads(previous.details_json)
            details.update(active=False, latest_check=check)
            previous.details_json = dump(details)
    return {'id':str(row.id),'agent':row.agent,'session_id':row.session_id,**data}


def registry_manager():
    from agent_manager.api.router import get_manager
    from types import SimpleNamespace
    try:
        # Share one current registry snapshot within this bounded pass only.
        entries = get_manager().list_skills()
        return SimpleNamespace(list_skills=lambda: entries)
    except (OSError, ValueError, RuntimeError):
        return None


def maintenance():
    from .sqlite_db import SessionLocal
    with SessionLocal() as db:
        manager = registry_manager()
        mark = db.get(AidrAuditState,'skill_usage_check')
        after = mark.value if mark else 0
        rows = db.query(AidrSkillUse).filter(AidrSkillUse.id > after, AidrSkillUse.expired_at.is_(None)).order_by(AidrSkillUse.id).limit(50).all()
        for row in rows: refresh(db,row,manager)
        end = rows[-1].id if rows else 0
        if mark: mark.value = end
        else: db.add(AidrAuditState(key='skill_usage_check',value=end))
        db.commit()


async def audit_loop():
    while True:
        try:
            await run_in_threadpool(maintenance)
        except Exception as exc:
            logging.getLogger(__name__).warning('Skill audit unavailable: %s',type(exc).__name__)
        await asyncio.sleep(10)
