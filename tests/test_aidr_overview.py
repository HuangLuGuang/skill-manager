"""Overview counters use durable evidence, independent sources and bounded projections."""
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy import event as sql_event
from tests.test_aidr_api import service
from tests.test_aidr_hook_queries import insert as hook_insert
from tests.test_aidr_operations import event, upload, behavior
from backend.aidr_models import AidrHookEvent
from backend.models import ClientTask
from backend.aidr_overview import (advance, overview, remove_evidence, OverviewOperation,
                                   OverviewEvidence, task_summary, invalidate_cache)

BASE = '/api/v1/clients/one/aidr/overview'
NOW = datetime.now(timezone.utc)


def hook(factory, n, kind='tool.pre', call='call', agent='codex', **changes):
    e = dict(agent=agent, session_id='session', turn_id='turn', native_call_id=call,
             tool='Bash', kind=kind, hook_event='PreToolUse' if kind=='tool.pre' else 'PostToolUse',
             behavior=behavior())
    e.update(changes)
    ident = hook_insert(factory, n, event=e)
    with factory() as db:
        row=db.get(AidrHookEvent, ident)
        raw=json.loads(row.payload_json); raw['received_at']=NOW.isoformat()
        row.payload_json=json.dumps(raw); db.commit()
    return ident


def drain(factory, limit=250):
    with factory() as db:
        while advance(db, limit): pass
    invalidate_cache()


def test_late_result_replay_and_retention_reconcile(service):
    client,factory=service
    pre=hook(factory, 1)
    drain(factory)
    with factory() as db:
        assert overview(db,'one',now=NOW)['totals']==dict(commands=1,tools=1,failures=0,sessions=1)
    post=hook(factory,2,'tool.failure')
    drain(factory); drain(factory)
    with factory() as db:
        assert overview(db,'one',now=NOW)['totals']['failures']==1
        assert db.query(OverviewOperation).count()==1
        remove_evidence(db,'hooks',[post]); db.get(AidrHookEvent,post).expired_at=datetime.utcnow(); db.commit()
        assert overview(db,'one',now=NOW)['totals']['failures']==0
        remove_evidence(db,'hooks',[pre]); db.get(AidrHookEvent,pre).expired_at=datetime.utcnow(); db.commit()
        assert overview(db,'one',now=NOW)['totals']['tools']==0
    drain(factory)
    with factory() as db: assert db.query(OverviewEvidence).count()==0


def test_source_scope_product_grouping_and_missing_identity(service):
    client,factory=service
    hook(factory,1,agent='qoder-cli')
    hook(factory,2,call='different',agent='qoder-hooks')
    hook(factory,3,native_call_id='')
    hook(factory,4,session_id='')
    raw=event('tool_call',schema_version=2,behavior=behavior(),user_scope='501',observed_at=NOW.isoformat())
    assert upload(client,raw).status_code==200
    assert upload(client,raw).status_code==200
    drain(factory,1)
    with factory() as db:
        stats=overview(db,'one',now=NOW)
        assert stats['totals']['tools']==2 and stats['unlinked']==2
        assert overview(db,'one',agent='qoder',now=NOW)['totals']['tools']==2
        assert overview(db,'one',source='logs',now=NOW)['totals']['tools']==1
        assert overview(db,'one',agent='claude',now=NOW)['totals']['tools']==0
    response=client.get(BASE)
    assert response.status_code==200,response.text
    assert 'PRIVATE-UNSEARCHABLE' not in response.text
    assert client.get(BASE.replace('/one/','/two/')).status_code==404
    assert client.get(BASE,params={'hours':721}).status_code==422
    details=client.get(BASE+'/details',params={'since':response.json()['since'],'until':response.json()['until']})
    assert details.status_code==200,details.text
    assert len(details.json()['items'])==2
    r=client.get(BASE+'/entry',params={'record_id':details.json()['items'][0]['record_id']})
    assert r.status_code==200,r.text
    assert 'PRIVATE-UNSEARCHABLE' not in r.text


def test_ambiguous_pre_events_and_reverse_arrival(service):
    _,factory=service
    hook(factory,1,'tool.failure')
    drain(factory)
    with factory() as db: assert overview(db,'one',now=NOW)['totals']['tools']==0
    hook(factory,2)
    drain(factory)
    with factory() as db: assert overview(db,'one',now=NOW)['totals']['failures']==1
    hook(factory,3)
    drain(factory)
    with factory() as db: assert overview(db,'one',now=NOW)['totals']['tools']==0


def test_initial_backfill_and_metadata_only_query(service):
    _,factory=service
    for i in range(1,5): hook(factory,i,call=str(i))
    with factory() as db:
        assert overview(db,'one',now=NOW)['state']=='preparing'
        advance(db,1)
        assert overview(db,'one',now=NOW)['state']=='preparing'
    drain(factory,1)
    statements=[]
    engine=factory.kw['bind']
    def record(conn,cursor,statement,parameters,context,executemany): statements.append(statement)
    sql_event.listen(engine,'before_cursor_execute',record)
    try:
        with factory() as db:
            assert overview(db,'one',now=NOW)['totals']['tools']==4
    finally: sql_event.remove(engine,'before_cursor_execute',record)
    assert not any('payload_json' in sql for sql in statements)
    assert len(statements)<=5


def test_task_history_does_not_promote_recovered_or_ancient_failures(service):
    client,factory=service
    with factory() as db:
        common=dict(client_id='one',task_type='aidr_plugin_action')
        p=json.dumps({'action':'install','agent':'codex'})
        rows=[ClientTask(**common,payload_json=p,status='failed',error='aidr_desktop_action_busy'),
              ClientTask(**common,payload_json=p,status='succeeded'),
              ClientTask(**common,payload_json=json.dumps({'action':'install','agent':'claude'}),status='failed',error='permission'),
              ClientTask(**common,status='failed',created_at=datetime.utcnow()-timedelta(days=8)),
              ClientTask(**common,status='running')]
        db.add_all(rows);db.commit()
        data=task_summary(db,'one')
        assert {r['id'] for r in data['attention']}=={rows[2].id,rows[4].id}
        assert len(data['history'])==5
    assert client.get(BASE+'/tasks').status_code==200
    assert client.get(BASE.replace('/one/','/two/')+'/tasks').status_code==404


def test_wrapper_command_classification():
    from backend.aidr_overview import command_name
    b=behavior();b['category']='wrapper'
    assert command_name(b)=='true'
    b['actions'].append(dict(category='command',command='pwd'))
    assert command_name(b)=='other'
    b['actions']=[]
    assert command_name(b)==''


def test_metadata_pagination_retention_and_worker_restart(service):
    from backend.aidr_retention import expire_once
    from tests.test_aidr_content import configure
    client,factory=service
    for n in range(1,34): hook(factory,n,call=str(n))
    drain(factory)
    stats=client.get(BASE).json()
    params={k:stats[k] for k in ('since','until')}
    first=client.get(BASE+'/details',params=params).json()
    second=client.get(BASE+'/details',params={**params,'cursor':first['next_cursor']}).json()
    ids=[r['record_id'] for r in first['items']+second['items']]
    assert len(ids)==len(set(ids))==33
    assert client.get(BASE+'/details',params={**params,'cursor':'invalid'}).status_code==422
    configure(factory,lifecycle={'enabled':True,'retention_days':1})
    with factory() as db:
        expire_once(db,datetime.utcnow()+timedelta(days=2))
        assert db.query(OverviewEvidence).count()==0
        assert db.query(OverviewOperation).count()==0
    drain(factory)
    assert client.get(BASE).json()['totals']['tools']==0


def test_two_workers_do_not_double_count(service):
    from concurrent.futures import ThreadPoolExecutor
    _,factory=service
    for n in range(1,16):hook(factory,n,call=str(n))
    def worker():
        with factory() as db:
            while advance(db,3):pass
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(lambda _:worker(),range(2)))
    with factory() as db:assert overview(db,'one',now=NOW)['totals']['tools']==15


def test_current_policy_receipt_is_required_to_resolve_older_policy_failure(service):
    from backend.runtime_governance import Observation
    from backend.client_governance import policy_view
    _,factory=service
    with factory() as db:
        version=policy_view(db,'one')['runtime_governance_version']
        failed=ClientTask(client_id='one',task_type='aidr_plugin_action',status='failed',payload_json=json.dumps({'action':'reconcile','policy_version':'old'}))
        success=ClientTask(client_id='one',task_type='aidr_plugin_action',status='succeeded',payload_json=json.dumps({'action':'reconcile','policy_version':version}))
        db.add_all([failed,success]);db.commit()
        report=Observation(client_id='one',reported_at=datetime.utcnow(),report_json=json.dumps({'policy_version':version,'policy_code':'aidr_desktop_policy_applied'}))
        db.add(report);db.commit()
        assert task_summary(db,'one')['attention']==[]
        report.reported_at=datetime.utcnow()-timedelta(minutes=5);db.commit()
        assert [r['id'] for r in task_summary(db,'one')['attention']]==[failed.id]
        report.reported_at=datetime.utcnow();report.report_json=json.dumps({'policy_version':'wrong','policy_code':'aidr_desktop_policy_applied'});db.commit()
        assert [r['id'] for r in task_summary(db,'one')['attention']]==[failed.id]


def test_old_and_new_discovery_reports_keep_unknown_separate_from_zero():
    from backend.routers.aidr import DiscoveryProgress
    base=dict(known_sources=1,pending_sources=0,pending_directories=0,scanned_entries=1,status='partial',reason_codes=['aidr_log_source_missing'])
    assert DiscoveryProgress.model_validate(base).historical_missing is None
    value=DiscoveryProgress.model_validate(dict(base,historical_missing=1,unread_missing=0,missing_directories=0))
    assert value.historical_missing==1 and value.unread_missing==0


def test_open_hour_excludes_future_events_from_totals_and_drilldown(service):
    from backend.aidr_overview import details
    _, factory = service
    now = NOW.replace(minute=20, second=0, microsecond=0)
    for n, at in enumerate((now-timedelta(hours=1), now, now+timedelta(minutes=5)), 1):
        ident = hook(factory, n, call=str(n))
        with factory() as db:
            row = db.get(AidrHookEvent, ident)
            raw = json.loads(row.payload_json)
            raw['received_at'] = at.isoformat()
            row.payload_json = json.dumps(raw)
            db.commit()
    drain(factory)
    with factory() as db:
        result = overview(db, 'one', now=now)
        assert result['totals']['tools'] == 2
        assert sum(r['commands']+r['other'] for r in result['trend']) == 2
        assert len(details(db, 'one', 'hooks', result['since'], result['until'])['items']) == 2
