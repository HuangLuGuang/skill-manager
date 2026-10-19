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
        assert overview(db,'one',now=NOW)['totals']==dict(commands=1,tools=1,failures=0,sessions=1,command_occurrences=1)
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


def test_bulk_expiry_matches_individual_reconciliation_without_per_row_queries(service):
    from sqlalchemy import select
    from backend.aidr_overview import OverviewBucket, OverviewCommandBucket, reconcile
    _, factory = service
    engine = factory.kw['bind']
    with factory() as db:
        common = dict(source='hooks', client_id='one', agent='codex', product='codex',
                      session_key='session', session_id='session', at=int(NOW.timestamp()),
                      tool='Bash', command='echo', command_counts_json='{"echo":2,"printf":1}')
        db.add_all([OverviewEvidence(**common, record_id=i, operation_key=str(i), phase='call', outcome='unknown')
                    for i in range(1, 102)])
        db.add(OverviewEvidence(**common, record_id=1002, operation_key='101', phase='result', outcome='failed'))
        db.flush()
        for i in range(1, 102):
            reconcile(db, str(i))
        db.commit()

        def snapshot():
            return [list(db.execute(select(model.__table__).order_by(model.__table__.c.key)).mappings())
                    for model in (OverviewOperation, OverviewBucket, OverviewCommandBucket)]

        statements = []
        def record(*args):
            statements.append(args[2])
        ids = [*range(1, 101), 1002]
        sql_event.listen(engine, 'before_cursor_execute', record)
        try:
            remove_evidence(db, 'hooks', ids)
        finally:
            sql_event.remove(engine, 'before_cursor_execute', record)
        assert len(statements) < 30
        actual = snapshot()
        assert len(actual[0]) == 1 and actual[0][0]['failed'] == 0
        assert actual[1][0]['calls'] == 1 and actual[1][0]['failures'] == 0
        assert sorted(r['occurrences'] for r in actual[2]) == [1, 2]
        db.rollback()

        # Applying removals one operation at a time must match grouped deltas,
        # including complete expiry and removal of only a failure result.
        evidence = OverviewEvidence.__table__
        db.execute(evidence.delete().where(evidence.c.source == 'hooks', evidence.c.record_id.in_(ids)))
        for i in range(1, 102):
            reconcile(db, str(i))
        assert snapshot() == actual
        db.rollback()


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
    assert details.json()['total']==2
    for filters, total in [({'source':'logs'},1), ({'agent':'qoder'},2), ({'agent':'codex'},0),
                           ({'dimension':'agents','value':'qoder'},2), ({'dimension':'tools','value':'Read'},0)]:
        result=client.get(BASE+'/details',params={'since':response.json()['since'],'until':response.json()['until'],**filters}).json()
        assert result['total']==total and len(result['items'])==total
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
    assert len(statements)<=7


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
    assert command_name(b)=='command'
    b['actions'].append(dict(category='command',command='pwd'))
    assert command_name(b)=='command'
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
    second=client.get(BASE+'/details',params={**params,'page':2}).json()
    ids=[r['record_id'] for r in first['items']+second['items']]
    assert len(ids)==len(set(ids))==33
    assert first['total']==second['total']==33
    assert first['page']==1 and second['page']==2 and first['page_size']==30
    jump=client.get(BASE+'/details',params={**params,'page':3,'page_size':10}).json()
    assert jump['page']==3 and jump['page_size']==10 and jump['total']==33
    assert jump['items']==first['items'][20:30]
    resized=client.get(BASE+'/details',params={**params,'page_size':50}).json()
    assert resized['total']==33 and len(resized['items'])==33
    last=client.get(BASE+'/details',params={**params,'page':999999999999999999999,'page_size':10}).json()
    assert last['page']==4 and len(last['items'])==3
    for invalid in ({'page':0},{'page':-1},{'page':'invalid'},{'page_size':0},{'page_size':101}):
        assert client.get(BASE+'/details',params={**params,**invalid}).status_code==422
    assert client.get(BASE.replace('/one/','/two/')+'/details',params=params).status_code==404
    configure(factory,lifecycle={'enabled':True,'retention_days':1})
    with factory() as db:
        expire_once(db,datetime.utcnow()+timedelta(days=2))
        assert db.query(OverviewEvidence).count()==0
        assert db.query(OverviewOperation).count()==0
    drain(factory)
    assert client.get(BASE).json()['totals']['tools']==0
    empty=client.get(BASE+'/details',params={**params,'page':4,'page_size':10}).json()
    assert empty==dict(items=[],total=0,page=1,page_size=10)


def test_session_pages_count_groups_and_preserve_scope(service):
    client,factory=service
    for n in range(1,8):
        hook(factory,n,call=str(n),session_id=f'session-{n//2}',agent='qoder-cli' if n<6 else 'codex')
    drain(factory)
    stats=client.get(BASE).json()
    params={k:stats[k] for k in ('since','until')}
    params.update(dimension='sessions',agent='qoder',page_size=2)
    first=client.get(BASE+'/details',params=params).json()
    second=client.get(BASE+'/details',params={**params,'page':2}).json()
    assert first['total']==second['total']==3
    assert len(first['items'])==2 and len(second['items'])==1
    assert len({r['key'] for r in first['items']+second['items']})==3
    assert all(r['agent']=='qoder-cli' for r in first['items']+second['items'])
    assert client.get(BASE+'/details',params={**params,'since':stats['until'],'until':stats['until']+3600}).json()['total']==0


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


def test_subcommand_occurrences_buckets_drilldown_and_retention(service):
    from backend.aidr_overview import details, OverviewCommandBucket
    client, factory = service
    b = behavior()
    b['actions'][0]['command'] = "sed -n '1,180p' a\nrg 'a|b' f && rg x f"
    pre = hook(factory, 1, behavior=b)
    hook(factory, 2, 'tool.post', behavior=b)  # Result cannot multiply occurrences.
    old = hook(factory, 3, call='old', behavior=b)
    with factory() as db:
        row = db.get(AidrHookEvent, old)
        raw = json.loads(row.payload_json)
        raw['received_at'] = (NOW-timedelta(hours=2)).isoformat()
        row.payload_json = json.dumps(raw)
        db.commit()
    drain(factory, 1); drain(factory, 1)
    with factory() as db:
        stats = overview(db, 'one', now=NOW)
        assert stats['totals']['tools'] == stats['totals']['commands'] == 2
        assert stats['totals']['command_occurrences'] == 6
        assert stats['rankings']['commands'] == [{'name': 'rg', 'count': 4}, {'name': 'sed', 'count': 2}]
        rows = details(db, 'one', 'hooks', stats['since'], stats['until'], dimension='commands', value='rg', page_size=1)
        assert rows['total'] == 2  # Two calls, although rg appears four times.
        assert len(rows['items']) == 1 and rows['items'][0]['command_counts'] == {'rg': 2, 'sed': 1}
        following = details(db, 'one', 'hooks', stats['since'], stats['until'], dimension='commands', value='rg', page=2, page_size=1)
        assert len(following['items']) == 1 and following['items'][0]['key'] != rows['items'][0]['key']
        assert details(db, 'one', 'hooks', stats['since'], stats['until'], dimension='commands', value="rg' OR 1=1 --")['items'] == []
        remove_evidence(db, 'hooks', [pre, old]); db.commit()
        stats = overview(db, 'one', now=NOW)
        assert stats['totals']['tools'] == stats['totals']['command_occurrences'] == 0
        assert db.query(OverviewCommandBucket).count() == 0


def test_capture_priority_and_unknown_preserve_tool_call_counts(service):
    _, factory = service
    b = behavior()
    b['contents'] = [{'kind': 'command_body', 'source_field': 'input.cmd', 'text': 'rg x\nrg y', 'truncated': False}]
    hook(factory, 1, behavior=b)
    b['contents'][0]['truncated'] = True
    hook(factory, 2, call='truncated', behavior=b)
    b['contents'][0].update(text='"$CMD" data', truncated=False)
    hook(factory, 3, call='dynamic', behavior=b)
    drain(factory)
    with factory() as db:
        stats = overview(db, 'one', now=NOW)
        assert stats['totals']['tools'] == stats['totals']['commands'] == 3
        assert stats['totals']['command_occurrences'] == 2
        assert stats['rankings']['commands'] == [{'name': 'rg', 'count': 2}]


def test_existing_overview_upgrade_rebuilds_only_projections(service):
    from backend.aidr_migrations import upgrade_aidr_schema
    _, factory = service
    ident = hook(factory, 1)
    drain(factory)
    with factory() as db:
        original = db.get(AidrHookEvent, ident).payload_json
    engine = factory.kw['bind']
    with engine.begin() as connection:
        for name in ('aidr_overview_evidence', 'aidr_overview_operations'):
            connection.exec_driver_sql(f'ALTER TABLE {name} DROP COLUMN command_counts_json')
    upgrade_aidr_schema(engine)
    with factory() as db:
        assert db.get(AidrHookEvent, ident).payload_json == original
        assert db.query(OverviewOperation).count() == 0
        assert overview(db, 'one', now=NOW)['state'] == 'preparing'
    drain(factory, 1)
    upgrade_aidr_schema(engine)
    with factory() as db:
        assert overview(db, 'one', now=NOW)['totals']['command_occurrences'] == 1
        assert db.get(AidrHookEvent, ident).payload_json == original
