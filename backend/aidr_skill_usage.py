"""Skill evidence and fresh registry checks; never participates in tool decisions."""
from . import aidr_adapters
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import PurePosixPath, PureWindowsPath

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm.attributes import set_committed_value

from . import aidr_policy, models
from .aidr_models import AidrEvent, AidrHookEvent, AidrSkillUse, AidrSkillCheck, skill_evidence_identity_columns
from .services.aidr_ingest import admission
from .services.gateway_db import run_sync
from agent_manager.core.signer import compute_content_digest, verify_signature, signature_content_digest, verify_content_digest

EVIDENCE_LOOKUP_BATCH = 32
AUDIT_BATCH_SIZE = 50
AUDIT_MAX_BATCHES = 4
AUDIT_PASS_SECONDS = 0.5
AUDIT_YIELD_SECONDS = 0.01
AUDIT_BUSY_SECONDS = 0.1
AUDIT_IDLE_SECONDS = 1


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def identity(client_id, event, source, record_id):
    # Entry identities stay distinct: shared Qoder Hooks do not identify CLI/IDE.
    parts = [client_id, event.get('user_scope') or ('unscoped:' + source), event.get('agent'), event.get('session_id'), event.get('native_agent_id', ''), event.get('native_call_id')]
    if aidr_adapters.get(event.get('agent')).turn_required:
        # Codex call identity is scoped to its native turn in the log contract.
        parts.append(event.get('turn_id') or ('unscoped:' + source))
    if not event.get('native_call_id') or not event.get('session_id'):
        parts += [source, str(record_id)]
    return hashlib.sha256(dump(parts).encode()).hexdigest()


def stage(event):
    if event.get('kind') == 'permission.denied' or (event.get('control_decision') or {}).get('decision') == 'deny':
        return 'denied'
    if event.get('kind') == 'tool.failure':
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


def aggregate_stage(evidence):
    results = {r['stage'] for r in evidence if r['kind'] in {'tool.post', 'tool_result', 'tool.failure', 'permission.denied'} or r['stage'] == 'denied'}
    if 'host_confirmed' in results and results & {'failed', 'denied'}:
        return 'unknown'
    return next((value for value in ('denied', 'failed', 'host_confirmed', 'unknown') if value in results), 'attempted')


def evidence_ref(source, record, event):
    return {'source': source, 'id': str(record.id), 'kind': event.get('kind'), 'stage': stage(event),
            'at': event.get('observed_at'), 'received_at': record.received_at.isoformat() + 'Z',
            'turn_id': event.get('turn_id') or '', 'tool': event.get('tool')}


def hydrate_evidence(db, row, data):
    refs, turns = [], set()
    for ref in data['evidence']:
        model = AidrHookEvent if ref['source'] == 'hook' else AidrEvent
        record = db.query(model).filter_by(id=int(ref['id']), client_id=row.client_id, expired_at=None).first()
        if record:
            raw = json.loads(record.payload_json)
            event = {**raw.get('event', {}), 'user_scope':raw.get('user_scope')} if ref['source'] == 'hook' else raw
            if identity(row.client_id, event, ref['source'], record.id) == row.call_key:
                refs.append(evidence_ref(ref['source'], record, event))
                if event.get('turn_id'):
                    turns.add(event['turn_id'])
                continue
        refs.append({**ref, 'available':False})
    data['evidence'] = refs
    # Legacy projections are repaired from exact native evidence only.
    if 'turn_id' not in data:
        data['turn_id'] = next(iter(turns)) if len(turns) == 1 else ''
    return data


def _evidence_candidates(model, client_id, event, *, visible_through=None):
    statement = select(model.id, model.payload_json, model.received_at).where(
        model.client_id == client_id, model.expired_at.is_(None))
    for column, field in zip(skill_evidence_identity_columns(model), ('agent', 'session_id', 'native_call_id')):
        statement = statement.where(column == event[field])
    if visible_through is not None:
        statement = statement.where(model.id <= visible_through)
    return statement.order_by(model.id).limit(65)


def _observation(source, record):
    raw = json.loads(record.payload_json)
    event = {**raw.get('event', {}), 'user_scope': raw.get('user_scope')} if source == 'hook' else raw
    return raw, event, identity(record.client_id, event, source, record.id)


def _batch_evidence(db, source, observations, known):
    lookups = []
    seen = set(known)
    for record, (_, event, key) in observations:
        if key in seen or not event.get('skill_use'):
            continue
        seen.add(key)
        if event.get('native_call_id') and event.get('session_id'):
            lookups.append((key, record, event))
    related = {}
    for model, kind in ((AidrEvent, 'log'), (AidrHookEvent, 'hook')):
        for start in range(0, len(lookups), EVIDENCE_LOOKUP_BATCH):
            group = lookups[start:start + EVIDENCE_LOOKUP_BATCH]
            queries = []
            for slot, (key, record, event) in enumerate(group):
                related[key, kind] = []
                candidates = _evidence_candidates(model, record.client_id, event,
                    visible_through=record.id if kind == source else None).subquery()
                queries.append(select(literal(slot).label('lookup_slot'), candidates))
            # Bound each native call separately before combining the queries;
            # another call's large history must not consume its evidence budget.
            for row in db.execute(union_all(*queries)):
                related[group[row.lookup_slot][0], kind].append(row)
            for key, _, _ in group:
                related[key, kind].sort(key=lambda row: row.id)
    return related


def merge_many(db, source, records):
    if not records:
        return
    client_id = records[0].client_id
    observations = [(record, _observation(source, record)) for record in records]
    keys = {observation[2] for _, observation in observations}
    known = {row.call_key: row for row in db.query(AidrSkillUse).filter(
        AidrSkillUse.client_id == client_id, AidrSkillUse.call_key.in_(keys)).all()}
    for start in range(0, len(observations), EVIDENCE_LOOKUP_BATCH):
        group = observations[start:start + EVIDENCE_LOOKUP_BATCH]
        related = _batch_evidence(db, source, group, known)
        for record, observation in group:
            merge(db, source, record, known=known, visible_through=record.id, related=related, observation=observation)

    if source == 'log' and any(event.get('agent') == 'codex' for _, (_, event, _) in observations):
        repair_codex_skill_projections(db, client_id)


def repair_codex_skill_projections(db, client_id):
    """Retire duplicate views, retaining their original evidence and checks."""
    from .aidr_operations import _record_identity, corrected_codex_records
    orphans = db.query(AidrSkillUse).filter_by(client_id=client_id, agent='codex', session_id='', expired_at=None).all()
    candidates = []
    for row in orphans:
        data = json.loads(row.payload_json)
        refs = data.get('evidence', [])
        if data.get('identity_ambiguous') or len(refs) != 1 or refs[0]['source'] != 'log':
            continue
        original = db.query(AidrEvent).filter_by(id=int(refs[0]['id']), client_id=client_id, expired_at=None).first()
        if original is None:
            continue
        event = json.loads(original.payload_json)
        if _record_identity(event) is not None:
            candidates.append((row, event))
    if not candidates:
        return 0
    corrected = corrected_codex_records(db.connection(), client_id, {e['source_instance_id'] for _, e in candidates})
    repaired = 0
    for row, event in candidates:
        matches = corrected.get(_record_identity(event), {})
        if len(matches) != 1:
            continue
        replacement = next(iter(matches.values()))
        target = db.query(AidrSkillUse).filter_by(client_id=client_id,
            call_key=identity(client_id, replacement, 'log', 0), expired_at=None).first()
        if target is None or json.loads(target.payload_json).get('identity_ambiguous'):
            continue
        row.expired_at = datetime.utcnow()
        repaired += 1
    return repaired


def merge(db, source, record, *, known=None, visible_through=None, related=None, observation=None):
    raw, event, key = observation if observation is not None else _observation(source, record)
    row = db.query(AidrSkillUse).filter_by(client_id=record.client_id, call_key=key).first() if known is None else known.get(key)
    skill = event.get('skill_use')
    if row is None and not skill:
        return
    if row and row.expired_at:
        return
    data = json.loads(row.payload_json) if row else {
        'skill': skill, 'stage': 'attempted', 'evidence': [], 'identity_ambiguous': False,
        'native_call_id': event.get('native_call_id', ''), 'native_agent_id': event.get('native_agent_id', ''),
        'turn_id': event.get('turn_id') or '',
        'entry': event.get('agent'), 'agent_version': event.get('agent_version') or None,
        'tool': event.get('tool'), 'user_scope': event.get('user_scope'),
        'first_at': event.get('observed_at') or raw.get('received_at') or record.received_at.isoformat() + 'Z',
    }
    ref = evidence_ref(source, record, event)
    if any(r['source'] == source and r['id'] == str(record.id) for r in data['evidence']):
        return
    if data.get('tool') and event.get('tool') and data['tool'] != event['tool']:
        data['identity_ambiguous'] = True
    if skill:
        old = data['skill']
        if any(old.get(k) and skill.get(k) and old[k] != skill[k] for k in ('name', 'path', 'behavior', 'content_digest')):
            data['identity_ambiguous'] = True
        else:
            data['skill'] = {**old, **{k:v for k,v in skill.items() if v}}
            if skill.get('content_status'):
                for field in ('content_digest', 'content_observed_at', 'content_status', 'content_reason'):
                    data['skill'].pop(field, None)
                    if skill.get(field):
                        data['skill'][field] = skill[field]
    if len(data['evidence']) < 64:
        data['evidence'].append(ref)
    else:
        data['identity_ambiguous'] = True
    data['stage'] = aggregate_stage(data['evidence'])
    if row is None:
        row = AidrSkillUse(client_id=record.client_id, call_key=key, agent=event['agent'], session_id=event.get('session_id',''),
                          behavior=skill['behavior'], payload_json=dump(data), received_at=record.received_at)
        db.add(row)
        db.flush()
        if known is not None:
            known[key] = row
        # Out-of-order uploads: join only exact native identity, within the same
        # entry/session. No timestamp or name-based association is performed.
        if event.get('native_call_id') and event.get('session_id'):
            for model, kind in ((AidrEvent,'log'),(AidrHookEvent,'hook')):
                candidates = related[key, kind] if related is not None else db.execute(_evidence_candidates(
                    model, record.client_id, event, visible_through=visible_through if kind == source else None))
                for candidate in candidates:
                    if kind == source and candidate.id == record.id:
                        continue
                    other = json.loads(candidate.payload_json)
                    other = {**other.get('event',{}), 'user_scope':other.get('user_scope')} if kind == 'hook' else other
                    if identity(record.client_id, other, kind, candidate.id) == key:
                        r = evidence_ref(kind, candidate, other)
                        if not any(v['source'] == kind and v['id'] == r['id'] for v in data['evidence']) and len(data['evidence']) < 64:
                            data['evidence'].append(r)
            data['stage'] = aggregate_stage(data['evidence'])
    row.payload_json = dump(data)
    row.next_check_at = datetime.utcnow()


def certification(db, row, manager):
    data = json.loads(row.payload_json)
    skill = data.get('latest_observation', {}).get('skill') or data['skill']
    cache = getattr(manager, 'checks', None)
    key = dump([row.client_id, row.agent, {k:v for k,v in skill.items() if k not in {'content_observed_at', 'content_status'}}, data.get('identity_ambiguous'), data.get('native_agent_id')])
    if cache is not None and key in cache:
        return {**cache[key], 'content_observed_at':skill.get('content_observed_at'), 'observation_task_id':data.get('latest_observation', {}).get('task_id')}
    value = _certification(db, row, manager)
    if cache is not None and len(cache) < 200:
        cache[key] = value
    return value


def _certification(db, row, manager):
    data = json.loads(row.payload_json)
    skill = data.get('latest_observation', {}).get('skill') or data['skill']
    result = {'status':'pending','reason':'source_unknown','registered':None,'approved':None,'revoked':None,
              'content_matches':None,'authorized':None,'managed_agent_id':None,'local_agent_id':None,
              'checked_at':datetime.utcnow().isoformat()+'Z', 'basis':'post_collection_content_observation',
              'content_observed_at':skill.get('content_observed_at'), 'observation_task_id':data.get('latest_observation', {}).get('task_id')}
    if data['identity_ambiguous']:
        return {**result, 'reason':'identity_ambiguous'}
    if not skill.get('path'):
        return result
    if not skill.get('content_digest'):
        reason = 'content_' + skill['content_reason'] if skill.get('content_reason') else 'content_digest_missing'
        return {**result, 'reason':reason}
    path_class = PureWindowsPath if PureWindowsPath(skill['path']).drive else PurePosixPath
    root = str(path_class(skill['path']).parent)
    installations = db.query(models.ClientSkillInstall).filter_by(client_id=row.client_id)
    if path_class is PureWindowsPath:
        installations = installations.filter(func.lower(func.replace(models.ClientSkillInstall.skill_path, '\\', '/')) == path_class(root).as_posix().lower())
    else:
        installations = installations.filter_by(skill_path=root)
    installations = installations.all()
    ids = {item.version_id or item.skill_id for item in installations if item.version_id or item.skill_id}
    if manager is None:
        raise RuntimeError('registry_unavailable')
    if len(ids) > 1:
        return {**result,'reason':'identity_ambiguous'}
    expected_id = next(iter(ids), None)
    entries = manager.list_certification_candidates(skill_id=expected_id, name=None if expected_id else skill.get('name'))
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
            digests[candidate.skill_id] = digest or getattr(manager, 'content_digest', compute_content_digest)(candidate.skill_path)
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
    verified = (getattr(manager, 'verify_digest', verify_content_digest)(skill['content_digest'], entry.signature) if signed_digest
                else bool(entry.signature and getattr(manager, 'verify_path', verify_signature)(entry.skill_path, entry.signature)))
    if not verified:
        return {**result,'reason':'signature_unverified'}
    # Inventory ownership is usable only for a unique product instance whose
    # configured Skill root contains this exact observed source.

    agents = db.query(models.ClientAgent).filter_by(client_id=row.client_id, agent_type=aidr_adapters.get(row.agent).inventory_type).all()
    agents = [a for a in agents if a.local_agent_id and any(
        p and path_class(root).is_relative_to(path_class(p))
        for p in (json.loads(a.capabilities_json or '{}').get('skill_roots') or [a.skills_path]))]
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


def refresh(db, row, manager, settings=None):
    return _apply_refresh(db, _prepare_refresh(db, row, manager, settings))


def refresh_batch(db, rows, manager, settings=None):
    """Compute fresh checks before opening the batch's write transaction.

    The caller commits the checks and alert updates together. Registry caches
    remain local to this request/pass; evidence is compared again on update.
    """
    policies = {}
    prepared = []
    for row in rows:
        if row.expired_at is not None:
            continue
        if row.client_id not in policies:
            policies[row.client_id] = settings if settings is not None else aidr_policy.current(db, row.client_id)['skill_audit']
        prepared.append(_prepare_refresh(db, row, manager, policies[row.client_id]))
    keys = [_alert_key(plan[0]) for plan in prepared]
    alerts = None

    def find_alert(key):
        nonlocal alerts
        # Called only after a successful conditional UPDATE owns the writer.
        # Reading before that point could miss another check's committed alert.
        if alerts is None:
            alerts = {event.aggregate_key: event for event in db.query(models.ClientEvent).filter(
                models.ClientEvent.aggregate_key.in_(keys)).all()}
        return alerts.get(key)

    return [_apply_refresh(db, plan, find_alert=find_alert) for plan in prepared]


def _prepare_refresh(db, row, manager, settings=None):
    original = row.payload_json
    data = json.loads(row.payload_json)
    if 'turn_id' not in data:
        data = hydrate_evidence(db, row, data)
    for ref in data['evidence']:
        if ref['kind'] == 'permission.denied':
            ref['stage'] = 'denied'
    data['stage'] = aggregate_stage(data['evidence'])
    settings = settings if settings is not None else aidr_policy.current(db,row.client_id)['skill_audit']
    try:
        check = certification(db, row, manager) if settings['enabled'] else {'status':'pending','reason':'audit_disabled','checked_at':datetime.utcnow().isoformat()+'Z'}
    except (OSError, ValueError, RuntimeError):
        check = {'status':'pending','reason':'query_failed','checked_at':datetime.utcnow().isoformat()+'Z'}
    previous_check = data.get('certification')
    data['certification'] = check
    return row, original, data, check, previous_check, settings


def _alert_key(row):
    return hashlib.sha256(('skill-use:' + row.client_id + ':' + row.call_key).encode()).hexdigest()


def _apply_refresh(db, prepared, *, find_alert=None):
    row, original, data, check, previous_check, settings = prepared
    next_check = datetime.utcnow() + timedelta(seconds=settings['status_refresh_seconds'])
    # A concurrent ingest must not lose new evidence to an older check snapshot.
    values = {'certification':check['status'], 'payload_json':dump(data), 'next_check_at':next_check}
    changed = db.query(AidrSkillUse).filter_by(id=row.id, payload_json=original, expired_at=None).update(
        values, synchronize_session=False)
    if not changed:
        db.expire(row)
        return {'id':str(row.id),'agent':row.agent,'session_id':row.session_id,**json.loads(row.payload_json)}
    # The conditional write succeeded; keep its exact persisted values without
    # reloading the whole payload while holding SQLite's writer. Rollback and
    # commit retain the Session's normal expiry behavior.
    for field, value in values.items():
        set_committed_value(row, field, value)
    if {k:v for k,v in (previous_check or {}).items() if k != 'checked_at'} != {k:v for k,v in check.items() if k != 'checked_at'}:
        db.add(AidrSkillCheck(client_id=row.client_id, usage_id=row.id,
            payload_json=dump({'check':check, 'observation':data.get('latest_observation') or {'skill':data['skill']}})))
    bad = {'unregistered','unapproved','revoked','content_changed','unauthorized'}
    rule = 'approval' if check['status'] in {'unregistered', 'unapproved', 'revoked'} else check['status']
    key = _alert_key(row)
    if settings['enabled'] and settings['alerts'] and check['status'] in bad and settings['alert_rules'].get(rule) == 'alert':
        details = {'active':True,'usage_id':str(row.id),'behavior':row.behavior,'stage':data['stage'],'reason_code':check['reason'],
                   'certification':check,'evidence':data['evidence']}
        values = dict(client_id=row.client_id,event_type='aidr_skill_alert',agent_type=row.agent,
                      skill_name=data['skill'].get('name') or check.get('name'),details_json=dump(details),
                      aggregate_key=key)
        stmt = insert(models.ClientEvent).values(**values)
        db.execute(stmt.on_conflict_do_update(index_elements=['aggregate_key'],set_={k:v for k,v in values.items() if k != 'aggregate_key'}))
    else:
        previous = find_alert(key) if find_alert is not None else db.query(models.ClientEvent).filter_by(aggregate_key=key).first()
        if previous:
            details = json.loads(previous.details_json)
            details.update(active=False, latest_check=check)
            previous.details_json = dump(details)
    return {'id':str(row.id),'agent':row.agent,'session_id':row.session_id,**data}


def registry_manager():
    from functools import lru_cache
    from types import SimpleNamespace

    @lru_cache(maxsize=200)
    def candidates(*, skill_id=None, name=None):
        from agent_manager.api.router import get_manager
        return get_manager().registry.list_certification_candidates(skill_id=skill_id, name=name)

    # Lazy, request-local snapshots: incomplete evidence needs no registry read.
    # A new request/batch reads current approval and revocation state again.
    return SimpleNamespace(list_certification_candidates=candidates, checks={},
                           content_digest=lru_cache(maxsize=200)(compute_content_digest),
                           verify_digest=lru_cache(maxsize=200)(verify_content_digest),
                           verify_path=lru_cache(maxsize=200)(verify_signature))


def maintenance():
    from .sqlite_db import SessionLocal
    with SessionLocal() as db:
        manager = registry_manager()
        rows = db.query(AidrSkillUse).filter(AidrSkillUse.next_check_at <= datetime.utcnow(), AidrSkillUse.expired_at.is_(None)).order_by(AidrSkillUse.next_check_at, AidrSkillUse.id).limit(AUDIT_BATCH_SIZE).all()
        if not rows:
            return False
        refresh_batch(db, rows, manager)
        db.commit()
        return db.query(db.query(AidrSkillUse).filter(
            AidrSkillUse.next_check_at <= datetime.utcnow(), AidrSkillUse.expired_at.is_(None)).exists()).scalar()


async def audit_loop():
    while True:
        more = False
        try:
            started = time.monotonic()
            for batch in range(AUDIT_MAX_BATCHES):
                if batch and time.monotonic() - started >= AUDIT_PASS_SECONDS:
                    break
                # Each batch closes its session and drops certification caches.
                # Share the bulk-work slots with uploads before occupying a
                # worker/connection. The shielded worker finishes its transaction
                # before cancellation releases this slot.
                async with admission():
                    more = await run_sync(maintenance)
                if not more or time.monotonic() - started >= AUDIT_PASS_SECONDS or batch + 1 == AUDIT_MAX_BATCHES:
                    break
                await asyncio.sleep(AUDIT_YIELD_SECONDS)
        except Exception as exc:
            logging.getLogger(__name__).warning('Skill audit unavailable: %s',type(exc).__name__)
            more = False
        await asyncio.sleep(AUDIT_BUSY_SECONDS if more else AUDIT_IDLE_SECONDS)
