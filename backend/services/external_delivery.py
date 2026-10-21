"""Durable outbound delivery of frozen Open API result events."""
import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy import exists

from .. import sqlite_db
from ..external_access_models import (ExternalAgentJob, ExternalPlatform, ExternalResultEvent, ExternalGatewayEvent, ExternalCallbackConfig, ExternalGatewayConfig,
    ExternalDeliveryEndpoint, ExternalDelivery, ExternalDeliveryAttempt)
from ..security_scan_controls import unprotect_secret
from ..models import ExternalAIGateway

logger = logging.getLogger(__name__)
EVENTS = {"callback": ExternalResultEvent, "gateway": ExternalGatewayEvent}
CONFIGS = {"callback": ExternalCallbackConfig, "gateway": ExternalGatewayConfig}


def locked(db):
    db.rollback()
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def digest(payload):
    return hashlib.sha256(payload.encode()).hexdigest() if payload is not None else None


def event_for(db, row):
    return db.query(EVENTS[row.kind]).filter_by(task_id=row.task_id).one()


def mirror(db, row):
    event = event_for(db, row)
    for name in ("status", "attempts", "last_attempt_at", "next_retry_at", "last_error_code"):
        setattr(event, name, getattr(row, name))
    if row.kind == "callback":
        event.delivered_at = row.completed_at if row.status == "delivered" else None
    else:
        event.synced_at = row.completed_at if row.status == "synced" else None
        event.receipt_id = json.loads(row.receipt_json).get("receipt_id") if row.receipt_json else None


def enqueue(db, *, task_id=None):
    for kind, model in EVENTS.items():
        query = db.query(model).filter(~exists().where(
            (ExternalDelivery.kind == kind) & (ExternalDelivery.task_id == model.task_id)))
        if task_id is not None:
            query = query.filter(model.task_id == task_id)
        events = query.limit(100).all()
        for event in events:
            payload = json.loads(event.payload_json) if event.payload_json else {}
            is_test = payload.get("event_type") in {"callback.test", "gateway.test"}
            job = db.get(ExternalAgentJob, event.task_id) if kind == "gateway" else None
            db.add(ExternalDelivery(delivery_id="od_" + uuid.uuid4().hex, kind=kind, task_id=event.task_id,
                purpose="test" if is_test else "result",
                task_type=payload.get("notification_type") or payload.get("task_type") or ("agent_evaluation" if kind == "gateway" else None),
                created_by=event.created_by,
                platform_id=event.source_platform_id if kind == "callback" else payload["platform_id"] if is_test else job.platform_id,
                business_request_id=payload.get("business_request_id") if kind == "callback" or is_test else job.business_request_id,
                config_id=event.callback_id if kind == "callback" else event.gateway_id,
                config_version=event.callback_version if kind == "callback" else event.gateway_version,
                message_id=payload.get("event_id" if kind == "callback" else "sync_id"),
                payload_sha256=digest(event.payload_json), status=event.status, attempts=event.attempts,
                last_attempt_at=event.last_attempt_at, next_retry_at=event.next_retry_at,
                last_error_code=event.last_error_code))
    db.flush()


def failure(db, row, code):
    row.status, row.last_error_code, row.next_retry_at = "failed", code, None
    row.lease_token = row.lease_until = None
    row.updated_at = datetime.utcnow()
    mirror(db, row)


def retry_or_fail(db, row, endpoint, code, retryable, retry_after=None):
    delays = json.loads(endpoint.retry_delays_json) if endpoint else []
    if retryable and row.cycle_attempts <= len(delays):
        delay = delays[row.cycle_attempts - 1]
        row.status, row.last_error_code = "retrying", code
        row.next_retry_at = datetime.utcnow() + timedelta(seconds=max(delay, retry_after or 0))
        row.lease_token = row.lease_until = None
        row.updated_at = datetime.utcnow()
        mirror(db, row)
    else:
        failure(db, row, code)


def claim():
    """Commit a lease and attempt before network I/O; other processes skip the lease."""
    with sqlite_db.SessionLocal() as db:
        locked(db)
        enqueue(db)
        now = datetime.utcnow()
        expired = db.query(ExternalDelivery).filter(ExternalDelivery.lease_until <= now).all()
        for row in expired:
            attempt = db.query(ExternalDeliveryAttempt).filter_by(delivery_id=row.delivery_id, number=row.attempts).one()
            attempt.status, attempt.error_code, attempt.finished_at = "interrupted", "DELIVERY_INTERRUPTED", now
            retry_or_fail(db, row, db.get(ExternalDeliveryEndpoint, row.endpoint_id), "DELIVERY_INTERRUPTED", True)
        rows = db.query(ExternalDelivery).filter(ExternalDelivery.status.in_(["pending", "retrying"]),
            ExternalDelivery.lease_token.is_(None),
            (ExternalDelivery.next_retry_at.is_(None)) | (ExternalDelivery.next_retry_at <= now)).order_by(
                ExternalDelivery.created_at, ExternalDelivery.delivery_id).limit(100).all()
        for row in rows:
            platform = db.get(ExternalPlatform, row.platform_id)
            endpoint = db.query(ExternalDeliveryEndpoint).filter_by(kind=row.kind, config_id=row.config_id,
                version=row.config_version).first()
            code = None
            config = db.get(CONFIGS[row.kind], row.config_id)
            if not platform or not platform.enabled:
                code = "DELIVERY_PARTNER_DISABLED"
            elif config and config.deleted_at:
                code = "DELIVERY_CONFIG_DELETED"
            elif config and not config.enabled:
                code = "DELIVERY_CONFIG_DISABLED"
            elif endpoint is None:
                code = "DELIVERY_CONFIG_MISSING"
            elif not endpoint.enabled:
                code = "DELIVERY_CONFIG_DISABLED"
            elif row.kind == "gateway" and endpoint.external_gateway_id is not None:
                gateway = db.get(ExternalAIGateway, endpoint.external_gateway_id)
                if not gateway or not gateway.enabled:
                    code = "DELIVERY_GATEWAY_UNAVAILABLE"
            if not code and row.platform_id not in json.loads(endpoint.platform_ids_json):
                code = "DELIVERY_FORBIDDEN"
            elif not code and row.kind == "callback" and row.task_type and row.task_type not in json.loads(endpoint.notification_types_json):
                code = "DELIVERY_FORBIDDEN"
            event = event_for(db, row)
            if not code and (not event.payload_json or digest(event.payload_json) != row.payload_sha256):
                code = "DELIVERY_SNAPSHOT_INVALID"
            if not code and len(event.payload_json.encode()) > endpoint.max_payload_bytes:
                code = "DELIVERY_PAYLOAD_TOO_LARGE"
            if code:
                failure(db, row, code)
                continue
            token_id = None
            try:
                if row.kind == "gateway" and endpoint.gateway_path:
                    from .external_gateways import receiver_url
                    if endpoint.url != receiver_url(gateway, endpoint.gateway_path):
                        failure(db, row, "DELIVERY_GATEWAY_ADDRESS_CHANGED")
                        continue
                    token_id = gateway.token_id
                    token = unprotect_secret(gateway.token_value_encrypted)
                else:
                    # Existing accepted deliveries retain their original Bearer receiver version.
                    token = unprotect_secret(endpoint.token_encrypted)
                if not token:
                    raise ValueError()
            except Exception:
                failure(db, row, "DELIVERY_CREDENTIAL_UNAVAILABLE")
                continue
            row.endpoint_id = endpoint.endpoint_id
            row.attempts += 1
            row.cycle_attempts += 1
            row.lease_token = uuid.uuid4().hex
            row.lease_until = now + timedelta(seconds=endpoint.timeout_seconds + 30)
            row.last_attempt_at = row.updated_at = now
            row.next_retry_at = None
            attempt = ExternalDeliveryAttempt(attempt_id="oa_" + uuid.uuid4().hex, delivery_id=row.delivery_id,
                number=row.attempts, status="sending", started_at=now)
            db.add(attempt)
            mirror(db, row)
            work = {"delivery_id": row.delivery_id, "lease_token": row.lease_token, "kind": row.kind,
                    "url": endpoint.url, "token": token, "timeout": endpoint.timeout_seconds,
                    "payload": event.payload_json, "token_id": token_id}
            db.commit()
            return work
        db.commit()
    return None


def receipt(kind, payload, body):
    if not isinstance(body, dict):
        return None
    if kind == "callback":
        if body.get("event_id") == payload["event_id"] and body.get("accepted") is True:
            return {"event_id": body["event_id"], "accepted": True}
        return None
    if payload.get("event_type") == "gateway.test":
        if body.get("sync_id") == payload["sync_id"] and body.get("accepted") is True:
            return {"sync_id": body["sync_id"], "accepted": True}
        return None
    if not isinstance(body.get("request_id"), str) or not 1 <= len(body["request_id"]) <= 128:
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    report = payload["report"]
    if (data.get("sync_id") != payload["sync_id"] or data.get("report_id") != report["report_id"]
            or type(data.get("report_version")) is not int or data["report_version"] != report["report_version"]
            or data.get("status") != "accepted" or type(data.get("current")) is not bool
            or not isinstance(data.get("receipt_id"), str) or not 1 <= len(data["receipt_id"]) <= 128):
        return None
    try:
        received = datetime.fromisoformat(data["received_at"].replace("Z", "+00:00"))
        if received.tzinfo is None:
            return None
    except (KeyError, AttributeError, TypeError, ValueError):
        return None
    return {key: data[key] for key in ("sync_id", "receipt_id", "report_id", "report_version", "status", "current", "received_at")}


def retry_after(value):
    if not value:
        return None
    try:
        seconds = int(value) if value.strip().isdigit() else (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        return max(0, min(seconds, (datetime.max - datetime.utcnow()).total_seconds() - 1))
    except (ValueError, TypeError, OverflowError):
        return None


async def transmit(work):
    result = {"http_status": None, "error_code": None, "retryable": False, "retry_after": None, "receipt": None}
    async def request():
        body = work["payload"].encode()
        headers = {"Content-Type": "application/json"}
        url = work["url"]
        if work.get("token_id") is not None:
            from ..external_ai_gateway import signed_request_url
            url = signed_request_url(url, "POST", body, work["token_id"], work["token"])
        else:
            headers["Authorization"] = "Bearer " + work["token"]
        async with httpx.AsyncClient(timeout=work["timeout"], follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", url, headers=headers, content=body) as response:
                result["http_status"] = response.status_code
                if response.status_code != 200:
                    result["error_code"] = "DELIVERY_HTTP_ERROR"
                    result["retryable"] = response.status_code in {408, 429} or 500 <= response.status_code < 600
                    if response.status_code == 429:
                        result["retry_after"] = retry_after(response.headers.get("Retry-After"))
                    return
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        result["error_code"] = "DELIVERY_RECEIPT_INVALID"
                        return
                try:
                    result["receipt"] = receipt(work["kind"], json.loads(work["payload"]), json.loads(raw))
                except (ValueError, TypeError):
                    pass
                if result["receipt"] is None:
                    result["error_code"] = "DELIVERY_RECEIPT_INVALID"
    try:
        await asyncio.wait_for(request(), timeout=work["timeout"])
    except (httpx.TimeoutException, asyncio.TimeoutError):
        result.update(error_code="DELIVERY_TIMEOUT", retryable=True)
    except httpx.RequestError:
        result.update(error_code="DELIVERY_NETWORK_ERROR", retryable=True)
    return result


def finish(work, result):
    with sqlite_db.SessionLocal() as db:
        locked(db)
        row = db.get(ExternalDelivery, work["delivery_id"])
        if row.lease_token != work["lease_token"]:
            return
        endpoint = db.get(ExternalDeliveryEndpoint, row.endpoint_id)
        attempt = db.query(ExternalDeliveryAttempt).filter_by(delivery_id=row.delivery_id, number=row.attempts).one()
        attempt.finished_at = row.updated_at = datetime.utcnow()
        attempt.http_status, attempt.error_code = result["http_status"], result["error_code"]
        if result["receipt"] is not None and result["error_code"] is None:
            row.status = "delivered" if row.kind == "callback" else "synced"
            row.completed_at = attempt.finished_at
            row.receipt_json = attempt.receipt_json = json.dumps(result["receipt"], ensure_ascii=False)
            row.last_error_code = row.next_retry_at = row.lease_token = row.lease_until = None
            mirror(db, row)
        else:
            retry_or_fail(db, row, endpoint, result["error_code"], result["retryable"], result["retry_after"])
        attempt.status = row.status
        db.commit()


async def delivery_loop():
    from starlette.concurrency import run_in_threadpool
    while True:
        try:
            work = await run_in_threadpool(claim)
            if work:
                result = await transmit(work)
                await run_in_threadpool(finish, work, result)
                continue
        except Exception as exc:
            logger.error("External delivery processing failed type=%s", type(exc).__name__)
        await asyncio.sleep(2)
