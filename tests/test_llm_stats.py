from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.api_errors import ApiError, api_error_handler
from backend.routers import llm_gateway
from backend.services import llm_stats
from backend.sqlite_db import Base, get_db


@pytest.fixture
def stats(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return cls(2026, 11, 4, 12)

    monkeypatch.setattr(llm_stats, 'datetime', Clock)
    engine = create_engine(f"sqlite:///{tmp_path / 'stats.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('PRAGMA journal_mode=WAL')
    factory = sessionmaker(bind=engine)
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(llm_gateway.admin_router)

    def db_dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[auth.get_current_admin_user] = lambda: SimpleNamespace(role='admin')
    with TestClient(app) as client:
        yield client, factory, engine
    engine.dispose()


def add_request(db, name, *, status='success', model='alpha', duration=100, at=None,
                tokens=None, recorded=None, pre=0, post=0, orphan=False, **identity):
    at = at or datetime(2026, 11, 3, 16)
    if not orphan:
        db.add(models.LlmRequestAudit(request_id=name, tenant_id='tenant', conversation_id='conv',
            user_ref='external-user', model=model, status=status, created_at=at,
            request_duration_ms=duration, upstream_duration_ms=duration*.8, platform_duration_ms=duration*.2,
            error='HTTP 503: Service Unavailable' if status == 'error' else None, **identity))
    if tokens is not None:
        db.add(models.LlmUsageMetric(request_id=name, tenant_id='tenant', conversation_id='conv',
            model=model, created_at=at, prompt_tokens=tokens, completion_tokens=10 if tokens else 0,
            total_tokens=tokens+10 if tokens else 0, usage_recorded=recorded,
            pre_compression_tokens=pre, post_compression_tokens=post,
            tokens_saved=1, api_key_id=identity.get('api_key_id')))


def test_dashboard_uses_one_request_set_and_preserves_missing_values(stats):
    client, factory, _ = stats
    with factory() as db:
        add_request(db, 'ok', tokens=50, pre=1000, post=200, recorded=True)
        add_request(db, 'zero', tokens=0, recorded=True, duration=200)
        add_request(db, 'missing', tokens=0, recorded=False, duration=0)
        add_request(db, 'old-zero', tokens=0, duration=0)
        add_request(db, 'failed', status='error', model='beta', duration=300)
        add_request(db, 'blocked', status='blocked', duration=400)
        add_request(db, 'orphan', tokens=40, orphan=True, duration=0)
        db.commit()
    result = client.get('/v1/llm-stats/dashboard', params={'days': 7}).json()
    overview = result['overview']
    assert overview['total_requests'] == 7
    assert overview['success_requests'] == 5
    assert overview['error_requests'] == overview['blocked_requests'] == 1
    assert overview['error_rate'] == 1/7
    assert overview['usage_requests'] == 3
    assert overview['total_tokens'] == 110
    assert overview['tokens_saved'] == 800  # Uses before/after, not historical capped savings.
    assert overview['compression_rate'] == .8
    assert overview['compression_coverage'] == .2
    assert overview['timed_requests'] == 4
    assert overview['avg_request_ms'] == 250
    assert overview['p95_request_ms'] == 400
    assert sum(row['total_requests'] for row in result['series']) == 7
    assert sum(row['total_requests'] for row in result['models']) == 7
    assert sum(row['total_requests'] for row in result['table']['items']) == 7
    assert client.get('/v1/llm-stats/overview', params={'days': 7}).json()['total_tokens'] == 110
    assert sum(r['requests'] for r in client.get('/v1/llm-stats/daily', params={'days': 7}).json()['series']) == 7
    failed = client.get('/v1/llm-stats/dashboard', params={'status': 'error', 'dimension': 'requests'}).json()
    assert failed['overview']['total_requests'] == failed['table']['total'] == 1
    assert failed['overview']['total_tokens'] is None
    assert failed['table']['items'][0]['total_tokens'] is None
    assert client.get('/v1/llm-stats/requests/zero').json()['total_tokens'] == 0
    for name in ('missing', 'old-zero'):
        assert client.get('/v1/llm-stats/requests/' + name).json()['total_tokens'] is None
    detail = client.get('/v1/llm-stats/requests/ok').json()
    assert detail['tokens_saved'] == 800 and detail['compression_recorded']
    assert not {'payload_json', 'prompt', 'response', 'user_ref'} & detail.keys()


def test_beijing_calendar_boundaries_and_day_filter(stats):
    from datetime import timedelta
    client, factory, _ = stats
    with factory() as db:
        for name, at in [('before', datetime(2026, 10, 28, 15, 59, 59)),
                         ('start', datetime(2026, 10, 28, 16)),
                         ('yesterday', datetime(2026, 11, 3, 15, 59, 59)),
                         ('today', datetime(2026, 11, 3, 16)),
                         ('end', datetime(2026, 11, 4, 15, 59, 59, 999999)),
                         ('after', datetime(2026, 11, 4, 16))]:
            add_request(db, name, at=at, tokens=10)
        for metric in db.query(models.LlmUsageMetric):
            metric.created_at += timedelta(seconds=2)
        db.commit()
    data = client.get('/v1/llm-stats/dashboard', params={'days': 7}).json()
    assert data['overview']['total_requests'] == 4
    assert data['start_date'] == '2026-10-29' and data['end_date'] == '2026-11-04'
    assert len(data['series']) == 7 and data['series'][-1]['total_requests'] == 2
    daily = client.get('/v1/llm-stats/daily', params={'days': 7}).json()['series']
    assert sum(item['requests'] for item in daily) == data['overview']['total_requests']
    assert next(item for item in daily if item['date'] == '2026-11-04')['requests'] == 2
    day = client.get('/v1/llm-stats/dashboard', params={'days': 7, 'day': '2026-11-04'}).json()
    assert day['overview']['total_requests'] == sum(r['total_requests'] for r in day['series']) == 2
    assert day['table']['items'][0]['requests'] == 2
    invalid = client.get('/v1/llm-stats/dashboard', params={'days': 7, 'day': '2026-10-01'})
    assert invalid.status_code == 422 and invalid.json()['error_code'] == 'gateway.stats.invalid_date'


def test_p95_server_sort_and_pagination(stats):
    client, factory, _ = stats
    with factory() as db:
        for i in range(1, 21):
            add_request(db, str(i), duration=i*100, tokens=i, model='alpha' if i <= 10 else 'beta')
        db.commit()
    data = client.get('/v1/llm-stats/dashboard', params={'dimension': 'requests', 'sort': 'avg_request_ms', 'page_size': 5, 'page': 2}).json()
    assert data['overview']['p95_request_ms'] == 1900
    assert data['table']['total'] == 20
    assert [r['request_duration_ms'] for r in data['table']['items']] == [1500, 1400, 1300, 1200, 1100]
    model = client.get('/v1/llm-stats/dashboard', params={'model': 'alpha'}).json()
    assert model['overview']['p95_request_ms'] == 1000
    assert model['overview']['total_requests'] == 10
    assert model['model_options'] == ['alpha', 'beta']
    empty = client.get('/v1/llm-stats/dashboard', params={'model': 'absent'}).json()
    assert empty['overview']['total_requests'] == empty['table']['total'] == 0
    assert empty['overview']['avg_request_ms'] is None
    assert empty['overview']['compression_rate'] is None
    assert client.get('/v1/llm-stats/dashboard', params={'sort': 'error;drop'}).status_code == 422
    assert client.get('/v1/llm-stats/dashboard', params={'page_size': 101}).status_code == 422


def test_credential_ownership_disambiguates_colliding_ids(stats):
    client, factory, _ = stats
    with factory() as db:
        db.add_all([models.User(id=1, username='alice', email='a@example.com', hashed_password='x'),
                    models.User(id=2, username='bob', email='b@example.com', hashed_password='x')])
        db.add(models.LlmApiKey(id=1, name='legacy', key_hash='legacy', key_prefix='legacy', user_id=1))
        db.add(models.AccessToken(id=1, name='new', token_hash='new', token_prefix='new', token_type='model_gateway', user_id=2))
        add_request(db, 'legacy', api_key_id=1, credential_type='legacy_llm_api_key', tokens=10)
        add_request(db, 'new', api_key_id=1, credential_type='model_gateway', tokens=20)
        add_request(db, 'ambiguous', api_key_id=1, tokens=30)
        db.commit()
    data = client.get('/v1/llm-stats/dashboard', params={'dimension': 'user'}).json()
    assert {r['user_id']: r['requests'] for r in data['table']['items']} == {0: 1, 1: 1, 2: 1}
    alice = client.get('/v1/llm-stats/dashboard', params={'user_id': 1, 'dimension': 'requests'}).json()
    assert alice['table']['items'][0]['request_id'] == 'legacy'
    assert alice['overview']['total_requests'] == 1
    unknown = client.get('/v1/llm-stats/dashboard', params={'user_id': 0}).json()
    assert unknown['overview']['total_requests'] == 1


def test_stats_requires_auth_and_returns_stable_missing_request_error(stats):
    client, _, _ = stats
    response = client.get('/v1/llm-stats/requests/not-found', headers={'Accept-Language': 'en-US'})
    assert response.status_code == 404 and response.json()['error_code'] == 'gateway.stats.request_not_found'
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    for path in ('dashboard', 'requests/not-found', 'overview', 'daily', 'by-model', 'by-user'):
        assert client.get('/v1/llm-stats/' + path).status_code == 401


def test_usage_flag_migration_is_idempotent_and_preserves_history(stats, monkeypatch):
    from backend import migrate_compression
    _, factory, engine = stats
    with factory() as db:
        add_request(db, 'old', tokens=0)
        db.commit()
    with engine.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE llm_usage_metrics DROP COLUMN usage_recorded')
    monkeypatch.setattr(migrate_compression, 'engine', engine)
    migrate_compression.migrate()
    migrate_compression.migrate()
    with factory() as db:
        metric = db.scalar(select(models.LlmUsageMetric))
        assert metric.request_id == 'old' and metric.usage_recorded is None
    with engine.connect() as conn:
        indexes = {row[1] for row in conn.exec_driver_sql('PRAGMA index_list(llm_request_audit)')}
        assert 'idx_llm_request_audit_created_at' in indexes


def test_statistics_keep_one_snapshot_during_concurrent_writes(stats):
    _, factory, _ = stats
    filters = llm_stats.StatsFilters(7, None, None, None, None)
    with factory() as writer:
        add_request(writer, 'first', tokens=10)
        writer.commit()
    with factory() as reader:
        source = llm_stats.request_rows(filters)
        assert llm_stats.aggregate(reader, source)[0]['total_requests'] == 1
        with factory() as writer:
            add_request(writer, 'second', tokens=20)
            writer.commit()
        assert llm_stats.grouped(reader, source, 'model')[0]['total_requests'] == 1
        assert llm_stats.requests_page(reader, source, 1, 10, 'created_at', True)['total'] == 1
    with factory() as reader:
        assert llm_stats.aggregate(reader, source)[0]['total_requests'] == 2


@pytest.mark.parametrize('custom', [False, True])
def test_stats_navigation_upgrade_preserves_custom_labels(stats, custom):
    from backend import iam, iam_models
    _, factory, _ = stats
    with factory() as db:
        db.add(iam_models.Menu(name='stats', is_system=True, title_zh='自定义' if custom else 'Token 压缩统计',
                               title_en='Custom' if custom else 'Token Compression'))
        db.commit()
        iam.initialize(db)
        iam.initialize(db)
        menu = db.get(iam_models.Menu, 'stats')
        assert menu.title_zh == ('自定义' if custom else '用量统计')
        assert menu.title_en == ('Custom' if custom else 'Usage Analytics')
        assert menu.title_key == (None if custom else 'iam.navigation.stats')


@pytest.mark.parametrize('usage,known', [(None, False), ({}, False), ({'input_tokens': None}, False),
                                       ({'input_tokens': 0, 'output_tokens': 0}, True)])
def test_protocol_adapters_preserve_absent_vs_explicit_zero_usage(usage, known):
    from backend.anthropic_compat import anthropic_to_openai_response, anthropic_stream_event_to_openai
    from backend.responses_upstream import responses_to_openai_response, ResponsesStreamAdapter
    for response in (anthropic_to_openai_response({'content': [], 'usage': usage}),
                     responses_to_openai_response({'status': 'completed', 'output': [], 'usage': usage}),
                     anthropic_stream_event_to_openai('message_start', {'message': {'usage': usage}})[0]):
        assert bool(response['usage']) is known
    events = ResponsesStreamAdapter().convert({'type': 'response.completed', 'response': {'status': 'completed', 'output': [], 'usage': usage}})
    assert bool(events[0]['usage']) is known


def test_randomized_request_ledger_matches_independent_calculations(stats):
    import math
    import random
    from collections import defaultdict
    from datetime import timedelta
    from statistics import mean

    client, factory, _ = stats
    rng = random.Random(20261104)
    ledger = []
    with factory() as db:
        for owner in range(1, 6):
            db.add(models.User(id=owner, username=f'owner-{owner}', email=f'{owner}@example.com', hashed_password='x'))
            db.add(models.AccessToken(id=owner, name=f'key-{owner}', token_type='model_gateway',
                token_hash=f'hash-{owner}', token_prefix=f'key-{owner}', user_id=owner))
        for index in range(240):
            name = f'generated-{index:04}'
            at = datetime(2026, 10, 5, 16) + timedelta(days=rng.randrange(31), seconds=rng.randrange(86400))
            owner = rng.randrange(6)
            model = f'model-{index % 17:02}'
            orphan = index % 19 == 0
            status = 'success' if orphan else rng.choice(['success', 'success', 'error', 'blocked'])
            has_metric = status == 'success' and index % 13 != 0
            flag = rng.choice([None, False, True])
            tokens = rng.randrange(1000) if has_metric and flag is not False and index % 7 else 0
            known = has_metric and (flag is True or tokens > 0)
            duration = 0 if orphan or index % 11 == 0 else rng.randrange(1, 50000)
            pre = rng.randrange(1, 10000) if has_metric and index % 3 else 0
            post = rng.choice([0, pre, pre // 2, pre + 10]) if pre else 0
            # Usage creation may cross midnight; an audited request follows its audit timestamp.
            if not orphan:
                db.add(models.LlmRequestAudit(request_id=name, tenant_id='test', conversation_id='test', user_ref='caller',
                    model=model, status=status, api_key_id=owner or None, credential_type='model_gateway',
                    created_at=at, request_duration_ms=duration, upstream_duration_ms=duration, platform_duration_ms=0))
            if has_metric:
                db.add(models.LlmUsageMetric(request_id=name, tenant_id='test', conversation_id='test', model=model,
                    api_key_id=owner or None, created_at=at if orphan else at + timedelta(seconds=2),
                    prompt_tokens=tokens, completion_tokens=tokens // 2, total_tokens=tokens + tokens // 2,
                    usage_recorded=flag, pre_compression_tokens=pre, post_compression_tokens=post))
            if orphan and not has_metric:
                continue
            ledger.append(dict(id=name, at=at, day=(at+timedelta(hours=8)).date().isoformat(), model=model,
                user_id=owner, status=status, known=known, tokens=tokens + tokens // 2,
                duration=duration or None, pre=pre, post=post, saved=max(0, pre-post)))
        db.commit()

    def check(actual, rows):
        durations = sorted(r['duration'] for r in rows if r['duration'] is not None)
        known = [r for r in rows if r['known']]
        before = sum(r['pre'] for r in rows)
        savings = sum(r['saved'] for r in rows)
        assert actual['total_requests'] == len(rows)
        for state in ('success', 'error', 'blocked'):
            assert actual[{'success': 'success_requests', 'error': 'error_requests', 'blocked': 'blocked_requests'}[state]] == sum(r['status'] == state for r in rows)
        assert actual['usage_requests'] == len(known)
        assert actual['total_tokens'] == (sum(r['tokens'] for r in known) if known else None)
        assert actual['avg_request_ms'] == (round(mean(durations), 2) if durations else None)
        assert actual['p95_request_ms'] == (durations[math.ceil(len(durations)*.95)-1] if durations else None)
        assert actual['tokens_saved'] == savings
        assert actual['pre_compression_tokens'] == before
        assert actual['post_compression_tokens'] == sum(r['post'] for r in rows)
        assert actual['compression_rate'] == (savings/before if before else None)

    for days in (7, 30):
        for condition in ({}, {'status': 'success'}, {'status': 'error'}, {'status': 'blocked'},
                          {'model': 'model-03'}, {'user_id': 0}, {'user_id': 2},
                          {'model': 'model-11', 'user_id': 4, 'status': 'success'}, {'day': '2026-11-03'}):
            selected = [r for r in ledger if datetime(2026, 11, 4, 16)-timedelta(days=days) <= r['at'] < datetime(2026, 11, 4, 16)
                        and all(r['day' if key == 'day' else key] == value for key, value in condition.items())]
            response = client.get('/v1/llm-stats/dashboard', params={'days': days, **condition, 'dimension': 'user', 'page_size': 100})
            assert response.status_code == 200, response.text
            data = response.json()
            check(data['overview'], selected)
            for dimension, items in [('model', data['models']), ('user_id', data['table']['items'])]:
                groups = defaultdict(list)
                for row in selected:
                    groups[row[dimension]].append(row)
                assert len(items) == len(groups)
                for item in items:
                    check(item, groups[item[dimension]])
            for daily in data['series']:
                subset = [r for r in selected if r['day'] == daily['date']]
                if subset:
                    check(daily, subset)
                else:
                    assert daily['total_requests'] == 0
    # Model grouping has more than one page; ordering is applied before pagination.
    data = client.get('/v1/llm-stats/dashboard', params={'days': 30, 'page': 2, 'page_size': 10, 'sort': 'total_requests', 'descending': False}).json()
    groups = defaultdict(list)
    for row in ledger:
        if datetime(2026, 10, 5, 16) <= row['at'] < datetime(2026, 11, 4, 16):
            groups[row['model']].append(row)
    ordered = sorted(groups, key=lambda name: (len(groups[name]), name))
    assert [r['model'] for r in data['table']['items']] == ordered[10:20]


    # New user columns sort across the full result set before pagination.
    users = client.get('/v1/llm-stats/dashboard', params={'days': 30, 'dimension': 'user', 'page_size': 100}).json()['table']['items']
    for sort in ('prompt_tokens', 'completion_tokens', 'compression_rate'):
        for descending in (True, False):
            expected = sorted(users, key=lambda row: (row[sort] is not None, row[sort] or 0, str(row['user_id'])), reverse=descending)
            result = client.get('/v1/llm-stats/dashboard', params={'days': 30, 'dimension': 'user', 'sort': sort, 'descending': descending, 'page_size': 2, 'page': 2}).json()
            assert result['table']['items'] == expected[2:4]


def test_ninety_day_user_breakdown_and_sorts(stats):
    client, factory, _ = stats
    with factory() as db:
        add_request(db, 'older', at=datetime(2026, 9, 1), tokens=200, pre=1000, post=400)
        add_request(db, 'recent', tokens=50, pre=100, post=90)
        add_request(db, 'outside', at=datetime(2026, 7, 1), tokens=900)
        db.commit()
    for sort in ('prompt_tokens', 'completion_tokens', 'compression_rate'):
        response = client.get('/v1/llm-stats/dashboard', params={'days': 90, 'dimension': 'user', 'sort': sort})
        assert response.status_code == 200
        result = response.json()
        user = result['table']['items'][0]
        assert result['overview']['total_requests'] == user['total_requests'] == 2
        assert user['prompt_tokens'] == 250
        assert user['completion_tokens'] == 20
        assert user['total_tokens'] == 270
        assert user['tokens_saved'] == 610
        assert user['compression_rate'] == pytest.approx(610 / 1100)
        assert client.get('/v1/llm-stats/dashboard', params={'dimension': 'requests', 'sort': sort}).status_code == 200
    assert client.get('/v1/llm-stats/dashboard', params={'days': 30}).json()['overview']['total_requests'] == 1


def test_custom_date_range_includes_both_beijing_days(stats):
    client, factory, _ = stats
    with factory() as db:
        for name, at in [('before', datetime(2026, 9, 30, 15, 59, 59)),
                         ('start', datetime(2026, 9, 30, 16)),
                         ('end', datetime(2026, 10, 2, 15, 59, 59, 999999)),
                         ('after', datetime(2026, 10, 2, 16))]:
            add_request(db, name, at=at, tokens=20)
        db.commit()
    params = {'start_date': '2026-10-01', 'end_date': '2026-10-02', 'days': 7, 'dimension': 'user'}
    result = client.get('/v1/llm-stats/dashboard', params=params)
    assert result.status_code == 200
    data = result.json()
    assert data['start_date'] == '2026-10-01' and data['end_date'] == '2026-10-02'
    assert len(data['series']) == 2
    assert data['overview']['total_requests'] == data['table']['items'][0]['total_requests'] == 2
    assert [row['total_requests'] for row in data['series']] == [1, 1]
    assert data['overview']['prompt_tokens'] == 40
    params['day'] = '2026-10-02'
    assert client.get('/v1/llm-stats/dashboard', params=params).json()['overview']['total_requests'] == 1
    params['day'] = '2026-10-03'
    assert client.get('/v1/llm-stats/dashboard', params=params).json()['error_code'] == 'gateway.stats.invalid_date'
    for invalid in ({'start_date': '2026-10-01'}, {'end_date': '2026-10-02'},
                    {'start_date': '2026-10-02', 'end_date': '2026-10-01'},
                    {'start_date': '2026-11-04', 'end_date': '2026-11-05'},
                    {'start_date': '2025-11-04', 'end_date': '2026-11-04'}):
        response = client.get('/v1/llm-stats/dashboard', params=invalid)
        assert response.status_code == 422
        assert response.json()['error_code'] == 'gateway.stats.invalid_range'
    assert client.get('/v1/llm-stats/dashboard', params={'days': 14}).status_code == 200
