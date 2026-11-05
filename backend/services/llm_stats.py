"""Request-based gateway statistics; all views share the same filtered relation."""
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import Query
from sqlalchemy import and_, case, func, literal, or_, select, union_all

from .. import models
from ..api_errors import ApiError


class StatsFilters:
    def __init__(
        self,
        days: int = Query(30, ge=1, le=365),
        model: str | None = Query(None, max_length=128),
        status: Literal["success", "error", "blocked"] | None = None,
        day: date | None = None,
        user_id: int | None = Query(None, ge=0),
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        self.days, self.model, self.status, self.day, self.user_id = days, model, status, day, user_id
        today = (datetime.utcnow() + timedelta(hours=8)).date()
        if start_date is not None or end_date is not None:
            if start_date is None or end_date is None or not today - timedelta(days=364) <= start_date <= end_date <= today:
                raise ApiError(422, "gateway.stats.invalid_range", "请选择最近365天内的完整日期范围", "Select a complete date range within the last 365 days")
            self.days = (end_date - start_date).days + 1
        else:
            end_date = today
            start_date = today - timedelta(days=days - 1)
        self.end = datetime.combine(end_date + timedelta(days=1), time()) - timedelta(hours=8)
        self.start = datetime.combine(start_date, time()) - timedelta(hours=8)
        if day and not start_date <= day <= end_date:
            raise ApiError(422, "gateway.stats.invalid_date", "所选日期不在统计周期内", "The selected date is outside the reporting period")


def request_rows(filters: StatsFilters):
    audit, metric = models.LlmRequestAudit, models.LlmUsageMetric
    # A metric can outlive its audit in historical data. Keep it once, as a successful request.
    columns = [
        audit.request_id, audit.created_at, audit.model, audit.status, audit.api_key_id,
        audit.credential_type, audit.error,
        case((audit.request_duration_ms > 0, audit.request_duration_ms)).label("request_duration_ms"),
        case((audit.request_duration_ms > 0, audit.upstream_duration_ms)).label("upstream_duration_ms"),
        case((audit.request_duration_ms > 0, audit.platform_duration_ms)).label("platform_duration_ms"),
    ]
    metric_columns = [metric.prompt_tokens, metric.completion_tokens,
                      case((metric.total_tokens > 0, metric.total_tokens),
                           else_=metric.prompt_tokens + metric.completion_tokens).label("total_tokens"),
                      metric.pre_compression_tokens, metric.post_compression_tokens,
                      metric.compression_duration_ms]
    # Old zero-filled records cannot establish whether upstream usage was returned.
    known_usage = or_(metric.usage_recorded.is_(True), and_(
        metric.usage_recorded.is_(None),
        or_(metric.prompt_tokens > 0, metric.completion_tokens > 0, metric.total_tokens > 0),
    ))
    audited = select(*columns, *metric_columns, known_usage.label("usage_recorded")).outerjoin(
        metric, metric.request_id == audit.request_id,
    ).where(audit.created_at >= filters.start, audit.created_at < filters.end)
    orphaned = select(
        metric.request_id, metric.created_at, metric.model, literal("success"), metric.api_key_id,
        literal(None), literal(None), literal(None), literal(None), literal(None),
        *metric_columns, known_usage,
    ).outerjoin(audit, audit.request_id == metric.request_id).where(
        audit.id.is_(None), metric.created_at >= filters.start, metric.created_at < filters.end,
    )
    requests = union_all(audited, orphaned).subquery()
    access, legacy, user = models.AccessToken, models.LlmApiKey, models.User
    owner = case(
        (requests.c.credential_type == "legacy_llm_api_key", legacy.user_id),
        (requests.c.credential_type.in_(["model_gateway", "agent_runtime"]), access.user_id),
        # Missing historical type is resolvable only if credential owners do not conflict.
        (and_(requests.c.credential_type.is_(None), or_(
            access.user_id.is_(None), legacy.user_id.is_(None), access.user_id == legacy.user_id,
        )), func.coalesce(access.user_id, legacy.user_id)),
    )
    query = select(*requests.c, func.coalesce(owner, 0).label("user_id"), user.username).select_from(
        requests.outerjoin(access, and_(access.id == requests.c.api_key_id, access.token_type.in_(["model_gateway", "agent_runtime"])))
        .outerjoin(legacy, legacy.id == requests.c.api_key_id).outerjoin(user, user.id == owner)
    )
    if filters.model:
        query = query.where(requests.c.model == filters.model)
    if filters.status:
        query = query.where(requests.c.status == filters.status)
    if filters.day:
        start = datetime.combine(filters.day, time()) - timedelta(hours=8)
        query = query.where(requests.c.created_at >= start, requests.c.created_at < start + timedelta(days=1))
    if filters.user_id is not None:
        query = query.where(func.coalesce(owner, 0) == filters.user_id)
    return query.subquery()


def read_snapshot(db):
    # SQLite's legacy driver does not begin a read transaction on SELECT.
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")


def beijing_day(column):
    # Some SQLite versions round fractional seconds into the next day during date arithmetic.
    return func.date(func.substr(column, 1, 19), "+8 hours")


def aggregate(db, source, group=None):
    read_snapshot(db)
    c = source.c
    compressed = and_(c.pre_compression_tokens > 0, c.post_compression_tokens >= 0)
    saved = case((c.pre_compression_tokens > c.post_compression_tokens,
                  c.pre_compression_tokens - c.post_compression_tokens), else_=0)
    fields = [
        func.count().label("total_requests"),
        func.sum(case((c.status == "success", 1), else_=0)).label("success_requests"),
        func.sum(case((c.status == "error", 1), else_=0)).label("error_requests"),
        func.sum(case((c.status == "blocked", 1), else_=0)).label("blocked_requests"),
        func.sum(case((c.usage_recorded.is_(True), 1), else_=0)).label("usage_requests"),
        *[func.sum(case((c.usage_recorded.is_(True), getattr(c, name)))).label(name)
          for name in ("prompt_tokens", "completion_tokens", "total_tokens")],
        func.sum(case((compressed, 1), else_=0)).label("compression_requests"),
        func.sum(case((compressed, c.pre_compression_tokens), else_=0)).label("pre_compression_tokens"),
        func.sum(case((compressed, c.post_compression_tokens), else_=0)).label("post_compression_tokens"),
        func.sum(case((compressed, saved), else_=0)).label("tokens_saved"),
        func.avg(case((compressed, c.compression_duration_ms))).label("avg_compression_ms"),
        func.count(c.request_duration_ms).label("timed_requests"),
        func.avg(c.request_duration_ms).label("avg_request_ms"),
        func.avg(c.upstream_duration_ms).label("avg_upstream_ms"),
        func.avg(c.platform_duration_ms).label("avg_platform_ms"),
    ]
    stmt = select(*fields).select_from(source)
    if group is not None:
        stmt = stmt.add_columns(group.label("group_key")).group_by(group)
    ranked = select(
        c.request_duration_ms.label("duration"),
        func.row_number().over(partition_by=group, order_by=c.request_duration_ms).label("rank"),
        func.count().over(partition_by=group).label("count"),
        (group if group is not None else literal(0)).label("group_key"),
    ).where(c.request_duration_ms.is_not(None)).subquery()
    percentiles = dict(db.execute(select(ranked.c.group_key, func.min(ranked.c.duration)).where(
        ranked.c.rank >= ranked.c.count * .95,
    ).group_by(ranked.c.group_key)).all())
    result = []
    for row in db.execute(stmt).mappings():
        item = dict(row)
        for name in ("total_requests", "success_requests", "error_requests", "blocked_requests",
                     "usage_requests", "compression_requests", "timed_requests", "pre_compression_tokens",
                     "post_compression_tokens", "tokens_saved"):
            item[name] = int(item[name] or 0)
        for name in ("avg_request_ms", "avg_upstream_ms", "avg_platform_ms", "avg_compression_ms"):
            item[name] = round(item[name], 2) if item[name] is not None else None
        item["p95_request_ms"] = percentiles.get(item.get("group_key", 0))
        item["error_rate"] = item["error_requests"] / item["total_requests"] if item["total_requests"] else None
        item["compression_rate"] = item["tokens_saved"] / item["pre_compression_tokens"] if item["pre_compression_tokens"] else None
        item["compression_coverage"] = item["compression_requests"] / item["success_requests"] if item["success_requests"] else None
        item["requests"] = item["total_requests"]
        item["avg_compression_ratio"] = item["compression_rate"]
        result.append(item)
    return result


def grouped(db, source, dimension):
    read_snapshot(db)
    key = source.c.model if dimension == "model" else source.c.user_id
    names = dict(db.execute(select(source.c.user_id, source.c.username).distinct()).all()) if dimension == "user" else {}
    items = aggregate(db, source, key)
    for item in items:
        value = item.pop("group_key")
        item[dimension if dimension == "model" else "user_id"] = value
        if dimension == "user":
            item["username"] = names.get(value)
    return items


def dashboard(db, filters, dimension, page, page_size, sort, descending):
    source = request_rows(filters)
    overview = aggregate(db, source)[0]
    daily = aggregate(db, source, beijing_day(source.c.created_at))
    daily_by_date = {item.pop("group_key"): item for item in daily}
    series = []
    for offset in range(filters.days):
        day = (filters.start + timedelta(hours=8, days=offset)).date().isoformat()
        series.append({"date": day, **daily_by_date.get(day, {"total_requests": 0, "success_requests": 0,
            "error_requests": 0, "blocked_requests": 0, "prompt_tokens": None, "completion_tokens": None,
            "pre_compression_tokens": 0, "post_compression_tokens": 0, "avg_request_ms": None, "p95_request_ms": None})})
    model_items = grouped(db, source, "model")
    model_items.sort(key=lambda r: (r["total_tokens"] or 0, r["model"]), reverse=True)
    if dimension == "requests":
        table = requests_page(db, source, page, page_size, sort, descending)
    else:
        items = model_items if dimension == "model" else grouped(db, source, "user")
        items = sorted(items, key=lambda r: (r[sort] is not None, r[sort] or 0, str(r.get("model", r.get("user_id")))), reverse=descending)
        table = {"items": items[(page-1)*page_size:page*page_size], "total": len(items)}
    # Options follow the period, retaining selected filters when results are empty.
    options = union_all(
        select(models.LlmRequestAudit.model).where(models.LlmRequestAudit.created_at >= filters.start, models.LlmRequestAudit.created_at < filters.end),
        select(models.LlmUsageMetric.model).where(models.LlmUsageMetric.created_at >= filters.start, models.LlmUsageMetric.created_at < filters.end),
    ).subquery()
    return {"overview": overview, "series": series, "models": model_items, "table": table,
            "model_options": list(db.scalars(select(options.c.model).distinct().order_by(options.c.model))),
            "start_date": (filters.start + timedelta(hours=8)).date().isoformat(),
            "end_date": (filters.end + timedelta(hours=8, days=-1)).date().isoformat(),
            "generated_at": datetime.utcnow().isoformat() + "Z"}


def request_item(row):
    item = dict(row)
    item["created_at"] = item["created_at"].isoformat() + "Z"
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if not item["usage_recorded"]:
            item[name] = None
    pre, post = item["pre_compression_tokens"], item["post_compression_tokens"]
    item["compression_recorded"] = pre is not None and pre > 0 and post is not None and post >= 0
    item["tokens_saved"] = max(0, pre-post) if item["compression_recorded"] else None
    return item


def requests_page(db, source, page, page_size, sort, descending):
    column = {"total_requests": source.c.created_at, "error_requests": source.c.status,
              "total_tokens": case((source.c.usage_recorded.is_(True), source.c.total_tokens)),
              "tokens_saved": case((source.c.pre_compression_tokens > 0,
                  case((source.c.pre_compression_tokens > source.c.post_compression_tokens,
                        source.c.pre_compression_tokens - source.c.post_compression_tokens), else_=0))),
              "avg_request_ms": source.c.request_duration_ms, "created_at": source.c.created_at}[sort]
    query = select(source).order_by(column.desc().nullslast() if descending else column.asc().nullsfirst(), source.c.request_id)
    return {"items": [request_item(row) for row in db.execute(query.offset((page-1)*page_size).limit(page_size)).mappings()],
            "total": db.scalar(select(func.count()).select_from(source))}
