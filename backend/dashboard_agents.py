"""Scoped platform charts and drilldowns over retained AIDR metadata."""
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import case, func, select, text, true

from . import models
from .aidr_models import AidrEvent, AidrHookEvent
from .aidr_overview import OverviewOperation, OverviewWatermark, OverviewCommandBucket
from .aidr_risk import RiskFinding, RiskCursor, SOURCES, RISK_CODES


def analytics(db, user, *, kind, source, days, now, details=False, page=1, page_size=10,
              client_id='', agent='', unknown_agent=False, scope='current', since=None, until=None,
              category='', tool='', program='', severity='', risk_code='', disposition='', sort_by='time', sort_order='desc'):
    clients = db.query(models.ManagedClient)
    if user.role != 'super_admin':
        clients = clients.filter(models.ManagedClient.registered_by == user.username)
    visible = clients.with_entities(models.ManagedClient.client_id).subquery()
    ids = select(visible.c.client_id)
    now_epoch = int(now.replace(tzinfo=timezone.utc).timestamp())
    end = now_epoch + 1
    start = int((now.replace(hour=0, minute=0, second=0, microsecond=0)
                 - timedelta(days=days - 1)).replace(tzinfo=timezone.utc).timestamp())
    start, end = since if since is not None else start, until if until is not None else end
    start_date, end_date = datetime.utcfromtimestamp(start), datetime.utcfromtimestamp(end)
    model = OverviewOperation if kind == 'behavior' else RiskFinding
    query = db.query(model).filter(model.client_id.in_(ids))
    if client_id:
        query = query.filter(model.client_id == client_id)
    agent_field = model.product if kind == 'behavior' else model.agent
    if agent:
        query = query.filter(agent_field == agent)
    if unknown_agent:
        query = query.filter(agent_field == '')
    if source:
        query = query.filter(model.source == source)
    if tool:
        query = query.filter(model.tool == tool)
    if kind == 'behavior':
        query = query.filter(model.at >= start, model.at < end,
                             model.at <= now_epoch)
        period = query
        if program:
            query = query.filter(text('EXISTS (SELECT 1 FROM json_each(aidr_overview_operations.command_counts_json) j WHERE j.key=:program)')).params(program=program)
        if category == 'commands':
            query = query.filter(model.command != '')
        elif category == 'other':
            query = query.filter(model.command == '')
        elif category == 'failures':
            query = query.filter(model.failed == 1)
    else:
        # Future-dated records must not enter the current snapshot either.
        query = query.filter(model.detected_at <= now)
        period = query.filter(model.detected_at >= start_date, model.detected_at < end_date)
        query = period if scope == 'period' else query.filter(model.disposition == 'open')
        for field, value in ((model.severity, severity), (model.risk_code, risk_code), (model.disposition, disposition)):
            if value:
                query = query.filter(field == value)
    if details:
        total = query.count()
        page = min(page, max(1, (total + page_size - 1) // page_size))
        time_field = model.at if kind == 'behavior' else model.detected_at
        key = model.key if kind == 'behavior' else model.id
        # Fetch only fields used by the table; evidence is read by existing scoped endpoints.
        fields = [key.label('id'), model.client_id, agent_field.label('agent'), model.source, model.tool]
        fields += [model.at, model.command, model.command_counts_json, model.failed, model.record_id] if kind == 'behavior' else [model.detected_at, model.severity, model.risk_code, model.disposition]
        sort_field = {'time': time_field, 'client_id': model.client_id, 'agent': agent_field,
                      'tool': model.tool, 'severity': RiskFinding.severity if kind == 'risk' else time_field}[sort_by]
        order = sort_field.asc() if sort_order == 'asc' else sort_field.desc()
        rows = query.with_entities(*fields).order_by(order, time_field.desc(), key.desc()).offset((page - 1) * page_size).limit(page_size).all()
        items = [dict(row._mapping) for row in rows]
        for item in items:
            if kind == 'risk':
                item['detected_at'] = item['detected_at'].replace(tzinfo=timezone.utc).isoformat()
            else:
                item['commands'] = json.loads(item.pop('command_counts_json'))
                item['record_id'] = str(item['record_id'])
        return dict(items=items, total=total, page=page, page_size=page_size)

    def counts(q, field, limit=None):
        rows = q.with_entities(field, func.count()).group_by(field).order_by(func.count().desc(), field)
        return [dict(key=value, value=count) for value, count in rows.limit(limit).all()]

    state = 'ready'
    updated = []
    sources = {source: {'hooks': AidrHookEvent, 'logs': AidrEvent}[source]} if kind == 'behavior' else SOURCES
    for name, raw in sources.items():
        maximum = db.query(func.max(raw.id)).filter(raw.client_id.in_(ids)).scalar() or 0
        cursor = db.get(OverviewWatermark if kind == 'behavior' else RiskCursor, name)
        stamp = (cursor.updated_at if kind == 'behavior' else int(cursor.checked_at.replace(tzinfo=timezone.utc).timestamp())) if cursor else None
        if maximum:
            if not cursor or cursor.position < maximum:
                state = 'preparing'
            elif stamp is not None and now_epoch - stamp > 60 and state == 'ready':
                state = 'delayed'
        if stamp:
            updated.append(stamp)
    result = dict(since=start, until=end, state=state, updated_at=min(updated) if updated else None,
                  clients=[dict(id=row.client_id, name=row.name, online=row.last_seen_at >= now - timedelta(minutes=10))
                           for row in clients.with_entities(models.ManagedClient.client_id, models.ManagedClient.name, models.ManagedClient.last_seen_at).order_by(models.ManagedClient.name).all()])
    day_field = func.date(model.at, 'unixepoch') if kind == 'behavior' else func.date(model.detected_at)
    daily = dict(period.with_entities(day_field, func.count()).group_by(day_field).all())
    result['trend'] = [dict(date=(start_date + timedelta(days=i)).date().isoformat(), value=daily.get((start_date + timedelta(days=i)).date().isoformat(), 0))
                       for i in range((end_date.date() - start_date.date()).days + (1 if end_date.time() != datetime.min.time() else 0))]
    if kind == 'behavior':
        complete_start, complete_end = (start + 3599) // 3600 * 3600, min(end, now_epoch + 1) // 3600 * 3600
        buckets = db.query(OverviewCommandBucket.program.label('program'), func.sum(OverviewCommandBucket.occurrences).label('n')).filter(
            OverviewCommandBucket.client_id.in_(ids), OverviewCommandBucket.source == source,
            OverviewCommandBucket.hour >= complete_start, OverviewCommandBucket.hour < complete_end)
        if client_id:
            buckets = buckets.filter(OverviewCommandBucket.client_id == client_id)
        if agent or unknown_agent:
            buckets = buckets.filter(OverviewCommandBucket.product == agent)
        boundary = period.filter((model.at < complete_start) | (model.at >= complete_end)).with_entities(model.command_counts_json).subquery()
        commands = func.json_each(boundary.c.command_counts_json).table_valued('key', 'value').alias('commands')
        edges = db.query(commands.c.key.label('program'), func.sum(commands.c.value).label('n')).select_from(boundary).join(commands, true()).group_by(commands.c.key)
        combined = buckets.group_by(OverviewCommandBucket.program).union_all(edges).subquery()
        ranks = db.query(combined.c.program, func.sum(combined.c.n)).group_by(combined.c.program).order_by(func.sum(combined.c.n).desc(), combined.c.program).limit(8).all()
        total, failures, command_calls = query.with_entities(func.count(), func.coalesce(func.sum(model.failed), 0),
            func.coalesce(func.sum(case((model.command != '', 1), else_=0)), 0)).one()
        result.update(total=total, failures=failures,
                      active_agents=query.with_entities(model.client_id, model.product).distinct().count(),
                      categories=[dict(key='commands', value=command_calls),
                                  dict(key='other', value=total-command_calls)],
                      tools=counts(query, model.tool, 8), commands=[dict(key=name, value=count) for name, count in ranks])
    else:
        result.update(total=query.count(), high=query.filter(model.severity == 'high').count(), new=period.count(), risk_codes=list(RISK_CODES),
                      severities=counts(query, model.severity), types=counts(query, model.risk_code),
                      dispositions=counts(period, model.disposition),
                      agents=[dict(client_id=client, agent=agent, value=count) for client, agent, count in
                              query.with_entities(model.client_id, model.agent, func.count()).group_by(model.client_id, model.agent)
                              .order_by(func.count().desc(), model.client_id, model.agent).limit(8).all()])
    return result
