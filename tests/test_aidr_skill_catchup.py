"""Bounded, off-loop audit catch-up with fresh checks and committed batches."""
import asyncio
import json
from datetime import datetime, timedelta
from threading import get_ident
from types import SimpleNamespace

import pytest

from backend import aidr_skill_usage as usage, models, sqlite_db
from backend.aidr_models import AidrSkillUse, AidrSkillCheck
from tests.test_aidr_api import service


def seed(factory, count, skill=None):
    with factory() as db:
        db.connection().exec_driver_sql('PRAGMA journal_mode=WAL')
        for i in range(count):
            db.add(AidrSkillUse(client_id='one',call_key=f'{i:064x}',agent='workbuddy',session_id='session',
                behavior='file_access',next_check_at=datetime.utcnow()-timedelta(seconds=count-i),
                payload_json=json.dumps({'skill':skill or {'name':'sample'},'evidence':[],
                    'turn_id':'','stage':'attempted','identity_ambiguous':False})))
        db.commit()


def test_catchup_commits_each_batch_and_reloads_revocation(service, monkeypatch, tmp_path):
    from agent_manager.core.signer import compute_signature, compute_content_digest
    _, factory = service
    root=tmp_path/'skill';root.mkdir();(root/'SKILL.md').write_text('benign')
    signature=compute_signature(root)
    seed(factory,120,dict(name='sample',path=str(root/'SKILL.md'),content_digest=compute_content_digest(root)))
    generations, threads, delays, committed = [], [], [], []
    def manager():
        threads.append(get_ident())
        generation=len(generations);generations.append(generation)
        entry=SimpleNamespace(skill_id='version',name='sample',family_id='family',version_no=1,
            skill_path=str(root),signature=signature,status='APPROVED' if generation==0 else 'RETIRED')
        return SimpleNamespace(list_certification_candidates=lambda **_:[entry],checks={})
    async def sleep(delay):
        delays.append(delay)
        with factory() as db:
            # Commit and session release must happen before yielding to writers.
            db.connection().exec_driver_sql('PRAGMA busy_timeout=100')
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            committed.append(db.query(AidrSkillCheck).count())
            db.rollback()
        if delay == usage.AUDIT_IDLE_SECONDS:
            raise asyncio.CancelledError
    monkeypatch.setattr(sqlite_db,'SessionLocal',factory)
    monkeypatch.setattr(usage,'registry_manager',manager)
    monkeypatch.setattr(usage,'time',SimpleNamespace(monotonic=lambda:0))
    monkeypatch.setattr(usage,'asyncio',SimpleNamespace(sleep=sleep))
    with pytest.raises(asyncio.CancelledError):asyncio.run(usage.audit_loop())
    assert delays == [.01,.01,1]
    assert committed == [50,100,120]
    assert len(generations)==3 and all(t!=get_ident() for t in threads)
    with factory() as db:
        rows=db.query(AidrSkillUse).order_by(AidrSkillUse.id).all()
        assert [r.certification for r in rows]==['verified_content']*50+['revoked']*70
        assert db.query(models.ClientEvent).count()==70


@pytest.mark.parametrize('outcomes,durations,expected', [
    ([True]*4,[.02]*4,[.01,.01,.01,.1]),
    ([True],[.6],[.1]),
    ([True],[.495],[.01,.1]),
    ([False],[.02],[1]),
    ([True,False],[.02,.02],[.01,1]),
    ([RuntimeError('private evidence')],[.02],[1]),
])
def test_pass_has_time_and_batch_budgets_and_error_backoff(monkeypatch, caplog, outcomes, durations, expected):
    clock=[0.0];calls=[];delays=[]
    async def run(_):
        index=len(calls);calls.append(index);clock[0]+=durations[index]
        value=outcomes[index]
        if isinstance(value,Exception):raise value
        return value
    async def sleep(delay):
        delays.append(delay);clock[0]+=delay
        if len(delays)==len(expected):raise asyncio.CancelledError
    monkeypatch.setattr(usage,'run_sync',run)
    monkeypatch.setattr(usage,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr(usage,'asyncio',SimpleNamespace(sleep=sleep))
    with pytest.raises(asyncio.CancelledError):asyncio.run(usage.audit_loop())
    assert delays==expected and len(calls)==len(outcomes)
    assert 'private evidence' not in caplog.text


def test_empty_future_and_expired_work_does_not_open_write_transaction(service, monkeypatch):
    from sqlalchemy import event
    _,factory=service
    seed(factory,2)
    with factory() as db:
        rows=db.query(AidrSkillUse).order_by(AidrSkillUse.id).all()
        rows[0].next_check_at=datetime.utcnow()+timedelta(hours=1)
        rows[1].expired_at=datetime.utcnow()
        db.commit()
    writes=[]
    def observe(_conn,_cursor,statement,_parameters,_context,_many):
        if statement.startswith(('UPDATE','INSERT','DELETE','BEGIN IMMEDIATE')):writes.append(statement)
    monkeypatch.setattr(sqlite_db,'SessionLocal',factory)
    event.listen(factory.kw['bind'],'before_cursor_execute',observe)
    try:assert usage.maintenance() is False
    finally:event.remove(factory.kw['bind'],'before_cursor_execute',observe)
    assert writes==[]


def test_failed_later_batch_preserves_previous_commit_and_retries_pending_work(service, monkeypatch):
    _,factory=service
    seed(factory,55)
    monkeypatch.setattr(sqlite_db,'SessionLocal',factory)
    original=usage._apply_refresh
    calls=[]
    def fail(db,plan,**kwargs):
        calls.append(plan[0].id)
        if len(calls)==53:raise OSError('audit write failed')
        return original(db,plan,**kwargs)
    monkeypatch.setattr(usage,'_apply_refresh',fail)
    assert usage.maintenance() is True
    with pytest.raises(OSError,match='audit write failed'):usage.maintenance()
    with factory() as db:
        assert db.query(AidrSkillCheck).count()==50
        assert db.query(AidrSkillUse).filter(AidrSkillUse.next_check_at<=datetime.utcnow()).count()==5
    monkeypatch.setattr(usage,'_apply_refresh',original)
    assert usage.maintenance() is False
    with factory() as db:assert db.query(AidrSkillCheck).count()==55


def test_concurrent_evidence_stays_due_and_is_retried(service, monkeypatch):
    _,factory=service
    seed(factory,1)
    monkeypatch.setattr(sqlite_db,'SessionLocal',factory)
    original=usage._apply_refresh
    def interleave(db,plan,**kwargs):
        with factory() as writer:
            row=writer.query(AidrSkillUse).one()
            data=json.loads(row.payload_json);data['new_evidence_marker']='late'
            row.payload_json=json.dumps(data);row.next_check_at=datetime.utcnow();writer.commit()
        return original(db,plan,**kwargs)
    monkeypatch.setattr(usage,'_apply_refresh',interleave)
    assert usage.maintenance() is True
    with factory() as db:
        assert db.query(AidrSkillCheck).count()==0
        assert json.loads(db.query(AidrSkillUse).one().payload_json)['new_evidence_marker']=='late'
    monkeypatch.setattr(usage,'_apply_refresh',original)
    assert usage.maintenance() is False
    with factory() as db:assert db.query(AidrSkillCheck).count()==1
