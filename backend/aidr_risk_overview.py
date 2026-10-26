"""Client risk aggregates over retained findings, without evidence content."""
import math
from datetime import datetime, timedelta

from sqlalchemy import func

from .aidr_risk import RiskFinding, summary, risk_products


def overview(db, client_id, days=7, offset_minutes=0, now=None, since=None, until=None, agent=""):
    now = now or datetime.utcnow()
    local_today = (now + timedelta(minutes=offset_minutes)).replace(hour=0, minute=0, second=0, microsecond=0)
    since = datetime.utcfromtimestamp(since) if since is not None else local_today - timedelta(days=days - 1, minutes=offset_minutes)
    until = datetime.utcfromtimestamp(until) if until is not None else now
    iso = lambda value: value.isoformat() + 'Z'
    base = db.query(RiskFinding).filter(RiskFinding.client_id == client_id)
    if agent:
        base = base.filter(RiskFinding.agent.in_(risk_products(agent)))
    current = dict(base.filter(RiskFinding.disposition == 'open').with_entities(
        RiskFinding.severity, func.count()).group_by(RiskFinding.severity).all())
    high, medium = current.get('high', 0), current.get('medium', 0)
    state = summary(db, client_id)
    availability = ('disabled' if not state['enabled'] else 'processing' if any(
        not p['caught_up'] or not p['fresh'] for p in state['progress']) else 'ready')
    if agent and not risk_products(agent):
        availability = 'unmapped'
    weight = high * 8 + medium * 3
    value = math.floor(100 * (1 - math.exp(-weight / 60)) + .5)
    period = base.filter(RiskFinding.detected_at >= since, RiskFinding.detected_at < until)
    def groups(field):
        return [{'key': key, 'count': count} for key, count in period.with_entities(
            field, func.count()).group_by(field).order_by(func.count().desc(), field).all()]
    day = func.date(RiskFinding.detected_at, f'{offset_minutes:+d} minutes')
    daily = {(date, severity): count for date, severity, count in period.with_entities(
        day, RiskFinding.severity, func.count()).group_by(day, RiskFinding.severity).all()}
    trend = []
    day_start = (since + timedelta(minutes=offset_minutes)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=offset_minutes)
    while day_start < until:
        start = max(since, day_start)
        label = (start + timedelta(minutes=offset_minutes)).date().isoformat()
        trend.append({'day': label, 'since': iso(start), 'before': iso(min(day_start + timedelta(days=1), until)),
                      'high': daily.get((label, 'high'), 0), 'medium': daily.get((label, 'medium'), 0)})
        day_start += timedelta(days=1)
    agents = {}
    for agent, severity, count in period.with_entities(RiskFinding.agent, RiskFinding.severity,
            func.count()).group_by(RiskFinding.agent, RiskFinding.severity).all():
        agents.setdefault(agent, {'key': agent, 'high': 0, 'medium': 0})[severity] = count
    return {'since': iso(since), 'before': iso(until), 'updated_at': iso(now), 'days': len(trend),
            'recent': [{'id': r.id, 'risk_code': r.risk_code, 'severity': r.severity, 'agent': r.agent,
                        'detected_at': iso(r.detected_at)} for r in base.filter(RiskFinding.disposition == 'open')
                       .order_by(RiskFinding.detected_at.desc(), RiskFinding.id.desc()).limit(3).all()],
            'score': {'state': availability, 'value': value if availability == 'ready' else None,
                      'high': high, 'medium': medium, 'weight': weight},
            'open': sum(current.values()), 'high_open': high,
            'new_24h': base.filter(RiskFinding.detected_at >= now - timedelta(hours=24),
                                  RiskFinding.detected_at < now).count(),
            'day_since': iso(now - timedelta(hours=24)),
            'total': period.count(), 'trend': trend, 'types': groups(RiskFinding.risk_code),
            'agents': sorted(agents.values(), key=lambda r: (-(r['high'] + r['medium']), r['key'])),
            'dispositions': groups(RiskFinding.disposition)}
