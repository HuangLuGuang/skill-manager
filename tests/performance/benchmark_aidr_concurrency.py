#!/usr/bin/env python3
"""Disposable full-backend AIDR / gateway / retention contention experiment.

Run with BENCHMARK_ISOLATED=YES. No existing service URL or database is accepted.
The client emulator persists frozen batches, pauses transport during an outage,
and removes batches only after checking the server's durable ACK and digest.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import inspect
import json
import os
import platform
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def encoded(value):
    return json.dumps(value, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    def percentile(p):
        pos = (len(values) - 1) * p
        lo = int(pos)
        return round(values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (pos - lo), 3)
    return dict(count=len(values), mean=round(sum(values) / len(values), 3),
                p50=percentile(.5), p95=percentile(.95), p99=percentile(.99), max=round(values[-1], 3))


def records(template, cid, start, count, policy, body_bytes, skills=None, skill_every=20):
    logs, hooks = [], []
    timestamp = datetime.utcnow().isoformat() + "Z"
    for seq in range(start, start + count):
        call = seq % 2 == 1
        identity = f"{cid}:{seq}"
        behavior = dict(version=5, policy=policy, category="command" if call else "unknown",
                        method="direct_fields" if call else "result_fields", actions=[],
                        status="unknown", result_basis=[], redacted=False, truncated=False, uncertainty=[],
                        contents=[dict(kind="command_body" if call else "tool_output",
                                       source_field="input.command" if call else "result.text", block=0,
                                       text=(("echo " if call else "done ") + "x" * body_bytes)[:body_bytes],
                                       source_bytes=body_bytes, redacted=False, truncated=False)],
                        content_status="captured")
        if call:
            behavior["actions"] = [dict(tool="Bash", category="command", command="", cwd="/tmp/benchmark",
                                        targets=[], source_fields=["command"])]
        event = {**template, "schema_version": 2, "agent": "codex",
                 "kind": "tool_call" if call else "tool_result", "tool": "Bash" if call else "",
                 "session_id": f"session-{cid}", "turn_id": f"turn-{(seq - 1) // 10}",
                 "native_call_id": f"call-{(seq - 1) // 2}", "source_id": digest(cid),
                 "logical_event_id": digest(identity), "event_id": digest("event:" + identity),
                 "content_digest": digest("content:" + identity), "observed_at": timestamp,
                 "record_offset": str(seq * 2048), "source_seq": str(seq * 2048), "block": 0,
                 "received_at": timestamp, "behavior": behavior}
        logs.append(dict(sequence=str(seq), kind="event", record_id=event["logical_event_id"], payload=event))
        hooks.append(dict(event_id=f"{seq:032x}", source_seq=str(seq), user_scope="501", received_at=timestamp,
                          event=dict(schema_version=3, agent="codex", hook_event="PreToolUse" if call else "PostToolUse",
                                     kind="tool.pre" if call else "tool.post", session_id=f"hook-session-{cid}",
                                     turn_id=event["turn_id"], native_call_id=event["native_call_id"], tool="Bash",
                                     policy=policy, behavior=behavior, contents=[], content_status="not_requested",
                                     evidence_digest=digest(identity), process_relation="unknown")))
        if skills and ((seq - 1) // 2) % skill_every == 0:
            skill = {**skills[((seq - 1) // (2 * skill_every)) % len(skills)], 'content_observed_at': timestamp}
            event['skill_use'] = skill
            hooks[-1]['event']['skill_use'] = skill
    return logs, hooks


def seed(directory, cfg):
    from backend import aidr_overview, aidr_policy
    from backend import models as m
    from backend.aidr_content import CaptureScope
    from backend.aidr_contract import Event
    from backend.aidr_hooks import HookRecord
    from backend.aidr_models import AidrHookEvent, AidrOperation, AidrSkillUse
    from backend.sqlite_db import SessionLocal
    template = next(v["event"] for v in json.loads((ROOT / "scanner/internal/aidr/agentlog/testdata/contracts.json").read_text()) if v["valid"])
    credentials = {f"bench-{i:03d}": secrets.token_urlsafe(32) for i in range(cfg["clients"])}
    credentials["model"] = secrets.token_urlsafe(32)
    credentials["mcp"] = secrets.token_urlsafe(32)
    def token(name, kind, scopes, **extra):
        return m.AccessToken(name=name, token_type=kind, token_hash=digest(credentials[name]), token_prefix="benchmark",
                             scopes_json=json.dumps(scopes), max_concurrent_requests=100, max_body_kb=1024, **extra)
    policy = dict(version="2", enabled=True, capture=dict(prompt=False, tool_output=True, file_body=False, command_body=True,
                  max_fragment_bytes=max(1024, cfg["body_bytes"]), max_event_bytes=max(2048, cfg["body_bytes"])),
                  lifecycle=dict(enabled=True, retention_days=1))
    policy["capture"] = CaptureScope.model_validate(policy["capture"]).model_dump()
    skills = []
    if cfg.get('skill_audit'):
        from agent_manager.api.router import get_manager
        from agent_manager.core.models import RegistryEntry
        from agent_manager.core.signer import compute_signature, compute_content_digest
        for i in range(10):
            root = directory / 'skills' / f'sample-{i}'
            root.mkdir(parents=True)
            (root / 'SKILL.md').write_text(f'---\nname: sample-{i}\n---\nBenchmark Skill {i}\n')
            get_manager().registry.add(RegistryEntry(skill_id=f'bench-skill-{i}', name=f'sample-{i}',
                description='Benchmark', source={}, skill_path=str(root), status='APPROVED', signature=compute_signature(root)))
            skills.append(dict(behavior='file_access', name=f'sample-{i}', path=str(root/'SKILL.md'),
                               basis='tool_input.path', content_digest=compute_content_digest(root), content_status='computed'))
        (directory / 'skills.json').write_bytes(encoded(skills))
    with SessionLocal() as db:
        for cid in list(credentials)[:cfg["clients"]]:
            db.add(m.ManagedClient(client_id=cid, name=cid, hostname=cid, os="darwin", arch="arm64", client_version="benchmark", registered_by="admin"))
            db.add(m.AidrDevice(client_id=cid, created_by="admin"))
            db.add(token(cid, "client", ["aidr:heartbeat", "aidr:report-events"], bound_client_id=cid, created_by="admin"))
            for i, skill in enumerate(skills):
                db.add(AidrSkillUse(client_id=cid, call_key=digest(f'seed:{cid}:{i}'), agent='codex',
                    session_id=f'skill-seed-{cid}', behavior='file_access', payload_json=json.dumps(dict(
                        skill={**skill, 'content_observed_at': datetime.utcnow().isoformat()+'Z'},
                        evidence=[], stage='attempted', identity_ambiguous=False, native_agent_id='', turn_id='seed'))))
        if skills:
            from backend.auth import create_access_token
            db.add(m.User(username='bench-admin', hashed_password='unused', role='super_admin', is_active=True))
            credentials['admin'] = create_access_token({'sub': 'bench-admin'})
        db.add(m.SystemConfig(key=aidr_policy.KEY, value=json.dumps(policy)))
        provider = m.ModelProvider(name="benchmark", base_url=f"http://127.0.0.1:{cfg['mock_port']}/v1", api_format="openai", enabled=True, timeout_seconds=10)
        db.add(provider)
        db.flush()
        db.add(m.ModelEndpoint(provider_id=provider.id, name="bench-model", display_name="Benchmark", enabled=True, is_default=True))
        db.add(token("model", "model_gateway", ["model:chat"], allowed_models_json='["bench-model"]'))
        db.add(m.PrivacyPolicy(name="Benchmark", enabled=False, entity_types_json="[]", entity_rules_json="{}", allow_bypass=True))
        schema = dict(type="object", properties={"text": {"type": "string"}}, required=["text"])
        schema_text = json.dumps(schema, separators=(",", ":"), sort_keys=True)
        server = m.McpServer(slug="bench", name="Benchmark", endpoint=f"http://localhost.:{cfg['mock_port']}/mcp", status="active", timeout_seconds=10)
        gateway = m.McpGateway(slug="benchmark", name="Benchmark", status="active")
        db.add_all([server, gateway])
        db.flush()
        db.add(m.McpTool(server_id=server.id, name="echo", exposed_name="bench__echo", description="echo", input_schema_json=schema_text,
                         schema_hash=digest(schema_text), enabled=True, risk_level="low", rate_limit_per_minute=100000, max_concurrent=100))
        db.add(m.McpGatewayBinding(gateway_id=gateway.id, server_id=server.id, allowed_tools_json='["echo"]', approved_schema_hashes_json=json.dumps({"echo": digest(schema_text)})))
        db.add(token("mcp", "mcp_gateway", ["mcp:connect", "mcp:list-tools", "mcp:call-tools"], allowed_mcp_gateways_json='["benchmark"]'))
        db.commit()
        # Historical bodies and projections are ready before the measured run.
        # Only the retention loops' first start is gated by the driver marker.
        old = datetime.utcnow() - timedelta(days=2)
        for base in range(0, cfg["historical_rows"], 500):
            log_rows, hook_rows, op_rows, pipeline_rows = [], [], [], []
            for i in range(base, min(base + 500, cfg["historical_rows"])):
                cid = f"bench-{i % cfg['clients']:03d}"
                logs, hooks = records(template, "old-" + cid, i + 1, 1, {**policy, "receipt": "a" * 32}, cfg["body_bytes"])
                event = logs[0]["payload"]
                if i == 0:
                    Event.model_validate(event)
                    HookRecord.model_validate(hooks[0])
                log_rows.append(dict(client_id=cid, logical_id=event["logical_event_id"], content_hash=digest(encoded(event)), agent="codex", kind=event["kind"], payload_json=encoded(event).decode(), received_at=old))
                hook_rows.append(dict(client_id=cid, stream_id="f" * 32, event_id=f"{i+1:032x}", source_seq=i+1, content_hash=digest(encoded(hooks[0])), payload_json=encoded(hooks[0]).decode(), received_at=old))
                op_rows.append(dict(client_id=cid, operation_key=digest(f"old:{i}"), agent="codex", session_id="old", tool="Bash", result_status="unknown", latest_at=old.isoformat(), payload_json=json.dumps({"call": event}), received_at=old))
                pipeline_rows.append(dict(request_id=f"old-{i}", stage="request", tenant_id="bench", conversation_id="old", model="bench-model", payload_json=json.dumps({"text": "x" * cfg["body_bytes"]}), expires_at=old))
            for model, rows in ((m.AidrEvent, log_rows), (AidrHookEvent, hook_rows), (AidrOperation, op_rows), (m.LlmPipelineTrace, pipeline_rows)):
                db.execute(model.__table__.insert(), rows)
            db.commit()
        db.add(m.RuntimeTraceSession(trace_id="old-runtime", tenant_id="bench", session_id="old", expires_at=old))
        db.commit()
        for base in range(0, cfg["historical_rows"], 500):
            db.execute(m.RuntimeTraceEvent.__table__.insert(), [dict(event_id=f"old-{i}", content_fingerprint=digest(str(i)), trace_id="old-runtime", seq=i+1,
                       event_time=old, tenant_id="bench", session_id="old", source="agent", type="tool.call") for i in range(base, min(base+500, cfg["historical_rows"]))])
            db.commit()
        while aidr_overview.advance(db):
            pass
    path = directory / "credentials.json"
    path.write_bytes(encoded(credentials))
    path.chmod(0o600)
    (directory / "template.json").write_bytes(encoded(template))


def serve(directory):
    cfg = json.loads((directory / "config.json").read_text())
    # Exercise license verification with a disposable signing identity as well.
    import base64

    import uvicorn
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from agent_manager.core.licensing import FEATURES, POLICY, LicenseStore, canonical
    key = Ed25519PrivateKey.generate()
    public = key.public_key()
    kid = digest(public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))[:16]
    keys = directory / "license-keys"
    keys.mkdir()
    (keys / f"{kid}.pem").write_bytes(public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    store = LicenseStore()
    identity = store.request("benchmark", "Disposable benchmark")
    payload = {**identity, "license_id": "LIC-" + secrets.token_hex(16), "revision": 1,
               "issued_at": "2026-01-01T00:00:00Z", "not_before": "2026-01-01T00:00:00Z",
               "expires_at": (datetime.utcnow() + timedelta(days=1)).isoformat() + "Z",
               "features": list(FEATURES), "limits": {"clients": cfg["clients"]}, "expiry_policy": POLICY}
    def b64(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    content = b64(canonical(payload))
    signature = b64(key.sign(f"am-license-v1.{kid}.{content}".encode()))
    store.import_license(canonical(dict(format="am-license-v1", key_id=kid, payload=content, signature=signature)), "benchmark")
    from backend import aidr_retention, main
    from backend.services.retention import retention_loop
    seed(directory, cfg)
    if cfg.get('skill_audit'):
        from backend import aidr_skill_usage
        original_maintenance = aidr_skill_usage.maintenance
        def measured_maintenance():
            started = time.time()
            error = None
            try:
                return original_maintenance()
            except Exception as exc:
                error = type(exc).__name__
                raise
            finally:
                with (directory / 'skill-maintenance.jsonl').open('a') as out:
                    out.write(json.dumps(dict(started=started, duration_ms=(time.time()-started)*1000, error=error))+'\n')
        aidr_skill_usage.maintenance = measured_maintenance
    import faulthandler
    from contextlib import asynccontextmanager, suppress
    original_lifespan = main.app.router.lifespan_context
    @asynccontextmanager
    async def instrumented_lifespan(app):
        with (directory / "blocked-stacks.log").open("w") as traces:
            async def watchdog():
                while True:
                    faulthandler.dump_traceback_later(5, file=traces)
                    started = time.perf_counter()
                    await asyncio.sleep(1)
                    lag = time.perf_counter() - started - 1
                    if lag > .1:
                        with (directory / "event-loop-lag.jsonl").open("a") as out:
                            out.write(json.dumps(dict(at=time.time(), lag_ms=lag * 1000)) + "\n")
            async with original_lifespan(app):
                watcher = asyncio.create_task(watchdog())
                try:
                    yield
                finally:
                    watcher.cancel()
                    with suppress(asyncio.CancelledError):
                        await watcher
                    faulthandler.cancel_dump_traceback_later()
    main.app.router.lifespan_context = instrumented_lifespan
    async def coordinated_loop(cleanup, name, **kwargs):
        while not (directory / "start-cleanup").exists():
            await asyncio.sleep(.1)
        def measured():
            started = time.time()
            more, error = None, None
            try:
                more = cleanup()
                return more
            except Exception as exc:
                error = type(exc).__name__
                raise
            finally:
                with (directory / "cleanup.jsonl").open("a") as out:
                    out.write(json.dumps(dict(name=name, started=started, duration_ms=(time.time()-started)*1000, more=more, error=error)) + "\n")
        async def measured_async():
            started = time.time()
            more, error = None, None
            try:
                more = await cleanup()
                return more
            except Exception as exc:
                error = type(exc).__name__
                raise
            finally:
                with (directory / "cleanup.jsonl").open("a") as out:
                    out.write(json.dumps(dict(name=name, started=started, duration_ms=(time.time()-started)*1000, more=more, error=error)) + "\n")
        await retention_loop(measured_async if inspect.iscoroutinefunction(cleanup) else measured, name, **kwargs)
    main.retention_loop = coordinated_loop
    aidr_retention.run_retention_loop = coordinated_loop
    if cfg.get("diagnostics"):
        from gateway_probe import install
        install(directory)
    uvicorn.run(main.app, host="127.0.0.1", port=cfg["port"], access_log=False, log_level="warning")


def snapshot(directory):
    with sqlite3.connect(f"file:{directory / 'backend.db'}?mode=ro", uri=True, timeout=2) as db:
        result = {}
        for table in ("aidr_events", "aidr_hook_events", "aidr_operations"):
            result[table] = dict(db.execute(f"SELECT CASE WHEN expired_at IS NULL THEN 'live' ELSE 'expired' END, count(*) FROM {table} GROUP BY 1"))
        for table, where in (("llm_pipeline_traces", "request_id LIKE 'old-%'"), ("runtime_trace_events", "trace_id='old-runtime'"), ("runtime_trace_sessions", "trace_id='old-runtime'")):
            result[table] = db.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]
        result["fresh_logs"] = db.execute("SELECT count(*) FROM aidr_events WHERE expired_at IS NULL AND received_at > datetime('now','-1 hour')").fetchone()[0]
        result["fresh_hooks"] = db.execute("SELECT count(*) FROM aidr_hook_events WHERE expired_at IS NULL AND received_at > datetime('now','-1 hour')").fetchone()[0]
        result["batch_records"] = {table: db.execute(f"SELECT coalesce(sum(record_count),0) FROM {table}").fetchone()[0] for table in ("aidr_batches", "aidr_hook_batches")}
        result['skill_audit'] = dict(zip(('total', 'due', 'oldest_due_seconds', 'unchecked'), db.execute(
            "SELECT count(*), coalesce(sum(next_check_at <= strftime('%Y-%m-%d %H:%M:%f','now')),0), "
            "max(0,coalesce((julianday('now')-julianday(min(next_check_at)))*86400,0)), "
            "coalesce(sum(json_extract(payload_json,'$.certification.checked_at') IS NULL),0) "
            "FROM aidr_skill_uses WHERE expired_at IS NULL").fetchone()))
    result["files_bytes"] = {name: (directory/name).stat().st_size if (directory/name).exists() else 0 for name in ("backend.db", "backend.db-wal")}
    return result


async def exercise(directory, cfg, pid):
    import httpx
    import psutil
    creds = json.loads((directory / "credentials.json").read_text())
    template = json.loads((directory / "template.json").read_text())
    skills = json.loads((directory / 'skills.json').read_text()) if cfg.get('skill_audit') else None
    base = f"http://127.0.0.1:{cfg['port']}"
    mock = f"http://127.0.0.1:{cfg['mock_port']}"
    samples, resources, phases, acknowledgments = [], [], [], []
    queues = {cid: asyncio.Queue() for cid in creds if cid.startswith("bench-")}
    policies = {}
    outbox = directory / "outbox"
    outbox.mkdir()
    online = asyncio.Event()
    online.set()
    state = dict(phase="warmup", generating=False, done=False, generated=0, acked=0, replayed=0, bad_acks=0, bytes=0)
    state['generated_skill_uses'] = 0
    upload_slots = asyncio.Semaphore(cfg["upload_concurrency"])
    replay_pending = set()
    replay = dict(reconnected_at=None, backlog_records=None, drained_at=None)
    process = psutil.Process(pid)
    driver = psutil.Process()
    process.cpu_percent()
    driver.cpu_percent()
    limits = httpx.Limits(max_connections=300, max_keepalive_connections=200)
    async with httpx.AsyncClient(timeout=35, limits=limits, trust_env=False) as client:
        for cid in queues:
            response = await client.post(base + f"/api/v1/clients/{cid}/aidr/audit-policy", json=dict(stream_id=digest(cid)[:32], last_sequence="0"),
                                         headers={"authorization": "Bearer " + creds[cid], "X-AIDR-Policy-Schema": "2", "X-AIDR-Audit-Lifecycle": "1", "X-AIDR-Content-Options": "1", **({'X-AIDR-Skill-Audit': '1'} if skills else {})})
            if response.status_code != 200:
                raise RuntimeError(f"Policy negotiation failed: {response.status_code} {response.text}")
            policies[cid] = response.json()

        async def request(kind, url, *, due=None, method='POST', **kwargs):
            phase = state["phase"]
            started = time.perf_counter()
            error = None
            response = None
            try:
                response = await client.request(method, url, **kwargs)
                status = str(response.status_code)
                body = response.json()
                if response.status_code != 200 or (kind == "mcp" and (body.get("error") or body.get("result", {}).get("isError"))):
                    error = body.get("error_code") or str(body.get("error", "unexpected_response"))[:160]
                if kind in ("llm", "direct") and response.status_code == 200 and body.get("choices", [{}])[0].get("message", {}).get("content") != "benchmark-ok":
                    error = "wrong_model_response"
                if kind == 'skill_list' and response.status_code == 200 and (
                    len(body.get('items', [])) != len(skills) or any(
                        item.get('certification', {}).get('status') != 'verified_content' for item in body.get('items', []))):
                    error = 'wrong_skill_certification'
            except Exception as exc:
                status, error = type(exc).__name__, type(exc).__name__
            end = time.perf_counter()
            samples.append(dict(phase=phase, kind=kind, status=status, error=error, latency_ms=(end-started)*1000,
                                scheduled_latency_ms=(end-(due or started))*1000, launch_lag_ms=(started-(due or started))*1000, at=time.time()))
            return response if error is None else None

        async def upload(cid):
            queue = queues[cid]
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return
                kind, path, created, count, batch_number = item
                raw = path.read_bytes()
                headers = {"authorization": "Bearer " + creds[cid], "content-type": "application/json"}
                if kind == "logs":
                    headers.update({"x-aidr-stream-id": digest(cid)[:32], "idempotency-key": digest(raw)})
                attempts = 0
                while True:
                    await online.wait()
                    async with upload_slots:
                        await online.wait()
                        response = await request(kind, base + f"/api/v1/clients/{cid}/aidr/" + ("events:batch" if kind == "logs" else "hooks:batch"), content=raw, headers=headers)
                    attempts += 1
                    if response is not None:
                        ack = response.json()
                        valid = ack.get("durable") is True and ack.get("digest") == digest(raw) and ack.get("accepted") == count
                        if not valid:
                            state["bad_acks"] += 1
                        elif batch_number % 10 == 0 and attempts == 1:
                            # Deliberately ignore a successful ACK, then replay identical bytes.
                            state["replayed"] += 1
                            continue
                        else:
                            acknowledgments.append(dict(kind=kind, phase=state["phase"], age_ms=(time.perf_counter()-created)*1000, records=count))
                            state["acked"] += count
                            path.unlink()
                            replay_pending.discard(path.name)
                            if replay["reconnected_at"] and not replay_pending and replay["drained_at"] is None:
                                replay["drained_at"] = time.time()
                            break
                    await asyncio.sleep(min(attempts, 5))
                queue.task_done()

        async def generate(cid, index):
            seq, number = 1, 0
            while not state["generating"]:
                await asyncio.sleep(.02)
            due = time.perf_counter() + index / cfg["clients"] * cfg["batch_seconds"]
            while state["generating"]:
                await asyncio.sleep(max(0, due-time.perf_counter()))
                if not state["generating"]:
                    break
                logs, hooks = records(template, cid, seq, cfg["batch_records"], policies[cid], cfg["body_bytes"], skills, cfg['skill_every'])
                state['generated_skill_uses'] += 2 * sum('skill_use' in r['payload'] and r['payload']['kind'] == 'tool_call' for r in logs)
                for kind, payload in (("logs", dict(schema_version=1, records=logs)),
                                      ("hooks", dict(schema_version=1, client_id=cid, stream_id=digest(cid)[:32], records=hooks))):
                    raw = encoded(payload)
                    path = outbox / f"{cid}-{kind}-{number}.json"
                    with path.open("wb") as f:
                        f.write(raw)
                        f.flush()
                        os.fsync(f.fileno())
                    await queues[cid].put((kind, path, due, cfg["batch_records"], number))
                    state["generated"] += cfg["batch_records"]
                    state["bytes"] += len(raw)
                seq += cfg["batch_records"]
                number += 1
                due += cfg["batch_seconds"]

        pending = set()
        async def page_load(kind):
            due, counter = time.perf_counter(), 0
            while not state['done']:
                await asyncio.sleep(max(0, due-time.perf_counter()))
                if state['done']:
                    break
                cid = f"bench-{counter % cfg['clients']:03d}"
                url = base + ('/api/v1/dashboard/overview' if kind == 'dashboard' else
                              f'/api/v1/clients/{cid}/aidr/skill-uses')
                params = {} if kind == 'dashboard' else dict(agent='codex', session_id=f'skill-seed-{cid}', limit=30)
                task = asyncio.create_task(request(kind, url, due=due, method='GET', params=params,
                                                  headers={'authorization': 'Bearer '+creds['admin']}))
                pending.add(task)
                task.add_done_callback(pending.discard)
                counter += 1
                due += 1 / cfg['page_rps']

        async def gateway_load(kind):
            due, counter = time.perf_counter(), 0
            while not state["done"]:
                await asyncio.sleep(max(0, due-time.perf_counter()))
                if state["done"]:
                    break
                if kind == "mcp":
                    url, data, token = base + "/mcp/benchmark", dict(jsonrpc="2.0", id=counter, method="tools/call", params=dict(name="bench__echo", arguments=dict(text="benchmark"))), creds["mcp"]
                else:
                    url = (mock if kind == "direct" else base) + "/v1/chat/completions"
                    data = dict(model="bench-model", messages=[dict(role="user", content=f"ping-{counter}")], metadata={"bypass_pii_check": "true", "conversation_id": f"bench-{counter}"})
                    token = creds["model"]
                task = asyncio.create_task(request(kind, url, due=due, json=data, headers={"authorization": "Bearer " + token}))
                pending.add(task)
                task.add_done_callback(pending.discard)
                due += 1 / cfg["gateway_rps"]
                counter += 1

        async def monitor():
            while not state["done"]:
                resources.append(dict(at=time.time(), phase=state["phase"], backend_cpu=process.cpu_percent(), backend_rss=process.memory_info().rss,
                                      driver_cpu=driver.cpu_percent(), driver_rss=driver.memory_info().rss,
                                      queued_records=state["generated"]-state["acked"], db=await asyncio.to_thread(snapshot, directory)))
                await asyncio.sleep(2)

        async def phase(name, seconds):
            state["phase"] = name
            begin = time.time()
            print(json.dumps(dict(phase=name, seconds=seconds, generated=state["generated"], acked=state["acked"])), flush=True)
            await asyncio.sleep(seconds)
            phases.append(dict(name=name, started=begin, ended=time.time(), generated=state["generated"], acked=state["acked"], db=await asyncio.to_thread(snapshot, directory)))

        workers = [asyncio.create_task(upload(cid)) for cid in queues]
        producers = [asyncio.create_task(generate(cid, i)) for i, cid in enumerate(queues)]
        gateways = [asyncio.create_task(gateway_load(kind)) for kind in ("llm", "mcp", "direct")]
        pages = [asyncio.create_task(page_load(kind)) for kind in ('skill_list', 'dashboard')] if skills else []
        monitor_task = asyncio.create_task(monitor())
        await phase("baseline", cfg["baseline_seconds"])
        state["generating"] = True
        await phase("steady", cfg["steady_seconds"])
        online.clear()
        await phase("offline", cfg["offline_seconds"])
        if cfg["cleanup_start"] == "replay":
            (directory / "start-cleanup").touch()
        replay_pending.update(p.name for p in outbox.iterdir())
        replay.update(reconnected_at=time.time(), backlog_records=state["generated"]-state["acked"])
        online.set()
        await phase("replay_cleanup" if cfg["cleanup_start"] == "replay" else "replay_control", cfg["replay_seconds"])
        await phase("recovery", cfg["recovery_seconds"])
        state["generating"] = False
        state["phase"] = "drain"
        for producer in producers:
            producer.cancel()
        await asyncio.gather(*producers, return_exceptions=True)
        drain_complete = True
        try:
            await asyncio.wait_for(asyncio.gather(*(q.join() for q in queues.values())), timeout=cfg["drain_seconds"])
        except asyncio.TimeoutError:
            drain_complete = False
        state["done"] = True
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        await asyncio.gather(*gateways, *pages)
        if pending:
            await asyncio.gather(*pending)
        await monitor_task
    summary = {}
    for name in [p["name"] for p in phases] + ["drain"]:
        summary[name] = {}
        for kind in ("logs", "hooks", "llm", "mcp", "direct", 'skill_list', 'dashboard'):
            rows = [s for s in samples if s["phase"] == name and s["kind"] == kind]
            summary[name][kind] = dict(latency_ms=distribution([s["latency_ms"] for s in rows]),
                                      scheduled_latency_ms=distribution([s["scheduled_latency_ms"] for s in rows]),
                                      launch_lag_ms=distribution([s["launch_lag_ms"] for s in rows]),
                                      statuses=dict(collections.Counter(s["status"] for s in rows)),
                                      errors=dict(collections.Counter(s["error"] for s in rows if s["error"])))
    final = snapshot(directory)
    cleanup_path = directory / "cleanup.jsonl"
    cleanup = [json.loads(line) for line in cleanup_path.read_text().splitlines()] if cleanup_path.exists() else []
    result = dict(config=cfg, environment=dict(platform=platform.platform(), python=sys.version, cpu_count=os.cpu_count(),
                  memory_bytes=psutil.virtual_memory().total, sqlite_version=sqlite3.sqlite_version, workers=1),
                  phases=phases, summary=summary, final=final, state=state, drain_complete=drain_complete,
                  integrity=dict(expected_per_channel=state["generated"]//2, persisted_logs=final["fresh_logs"], persisted_hooks=final["fresh_hooks"],
                                 remaining_outbox_files=len(list(outbox.iterdir())), bad_acks=state["bad_acks"]),
                  ack_age_ms={kind: distribution([a["age_ms"] for a in acknowledgments if a["kind"] == kind]) for kind in ("logs", "hooks")},
                  resources=resources, cleanup=cleanup, replay=replay)
    (directory / "requests.jsonl").write_text("".join(json.dumps(s)+"\n" for s in samples))
    (directory / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(dict(result=str(directory / "result.json"), integrity=result["integrity"], drain_complete=drain_complete)), flush=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    if os.environ.get("BENCHMARK_ISOLATED") != "YES":
        raise SystemExit("BENCHMARK_ISOLATED=YES is required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--mock", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-start", choices=("replay", "disabled"), default="replay")
    parser.add_argument("--source-root", type=Path, default=ROOT, help="Optional existing benchmark source snapshot")
    parser.add_argument("--diagnostics", action="store_true", help="Record DB phases, worker waits and transport errors")
    parser.add_argument('--skill-audit', action='store_true', help='Add real signed Skill checks and authenticated UI queries')
    for name, default in (("clients", 100), ("upload-concurrency", 100), ("historical-rows", 10000), ("body-bytes", 1024), ("batch-records", 10), ("batch-seconds", 5),
                          ("gateway-rps", 5), ("baseline-seconds", 20), ("steady-seconds", 30), ("offline-seconds", 20),
                          ("replay-seconds", 60), ("recovery-seconds", 20), ("drain-seconds", 120), ('skill-every', 20), ('page-rps', 1)):
        parser.add_argument("--" + name, type=int, default=default)
    args = parser.parse_args()
    if args.server:
        serve(args.server)
        return
    if args.mock:
        from http.server import ThreadingHTTPServer

        from mock_upstreams import Handler
        ThreadingHTTPServer(("127.0.0.1", args.mock), Handler).serve_forever()
        return
    cfg = {k: v for k, v in vars(args).items() if k not in ("server", "mock", "source_root")}
    if any(v <= 0 for v in cfg.values() if type(v) is int) or cfg["batch_records"] % 2 or cfg["body_bytes"] > 32768:
        parser.error("values must be positive; batch-records must be even")
    cfg.update(port=free_port(), mock_port=free_port())
    directory = Path(tempfile.mkdtemp(prefix="aidr-benchmark-"))
    # Freeze the tested source so concurrent workspace edits cannot change a run.
    source = directory / "source"
    for name in ("backend", "agent_manager"):
        shutil.copytree(args.source_root / name, source / name, ignore=shutil.ignore_patterns(".venv", "__pycache__", ".env", "*.db", "*.db-wal", "*.db-shm"))
    script = source / "tests/performance" / Path(__file__).name
    script.parent.mkdir(parents=True)
    shutil.copy2(__file__, script)
    shutil.copy2(Path(__file__).with_name("mock_upstreams.py"), script.with_name("mock_upstreams.py"))
    shutil.copy2(Path(__file__).with_name("gateway_probe.py"), script.with_name("gateway_probe.py"))
    vector = Path("scanner/internal/aidr/agentlog/testdata/contracts.json")
    (source / vector).parent.mkdir(parents=True)
    shutil.copy2(args.source_root / vector, source / vector)
    manifest = {str(p.relative_to(source)): digest(p.read_bytes()) for p in sorted(source.rglob("*")) if p.is_file()}
    cfg["source_sha256"] = digest(encoded(manifest))
    cfg["git_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (directory / "source-manifest.json").write_bytes(encoded(manifest))
    (directory / "config.json").write_bytes(encoded(cfg))
    # An explicit local policy prevents discovery of the user's home policy.
    (directory / "company-policy.yaml").write_text("{}\n")
    env = {key: os.environ[key] for key in ("PATH", "LANG", "SYSTEMROOT", "TMPDIR") if key in os.environ}
    env.update(BENCHMARK_ISOLATED="YES", PYTHONPATH=str(source), PYTHON_DOTENV_DISABLED="1", PYTHONUNBUFFERED="1",
               NO_PROXY="*", HTTP_PROXY="", HTTPS_PROXY="", ALL_PROXY="",
               SQLITE_PATH=str(directory / "backend.db"), AGENT_MANAGER_REGISTRY_SQLITE_PATH=str(directory / "backend.db"),
               DATA_DIR=str(directory / "data"), UPLOADS_DIR=str(directory / "uploads"),
               AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH=str(directory / "signing.pem"), SECRET_KEY=secrets.token_hex(32),
               AGENT_MANAGER_LICENSE_KEYS_DIR=str(directory / "license-keys"),
               AGENT_MANAGER_LICENSE_STATE_PATH=str(directory / "license.db"),
               INITIAL_ADMIN_PASSWORD=secrets.token_urlsafe(32), AGENT_SECURITY_SCANNING_ENABLED="false",
               MCP_ALLOW_HTTP="true", MCP_OUTBOUND_ALLOWLIST="127.0.0.1,::1", BENCH_UPSTREAM_DELAY_MS="50")
    children = []
    print(json.dumps(dict(workspace=str(directory))), flush=True)
    try:
        for name, mode, value in (("mock", "--mock", cfg["mock_port"]), ("backend", "--server", directory)):
            with (directory / f"{name}.log").open("wb") as log:
                children.append(subprocess.Popen([sys.executable, str(script), mode, str(value)], cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT))
        import httpx
        ready = False
        for _ in range(600):
            if children[-1].poll() is not None:
                raise RuntimeError(f"Backend exited; inspect {directory / 'backend.log'}")
            try:
                response = httpx.get(f"http://127.0.0.1:{cfg['port']}/api/auth/captcha", timeout=1, trust_env=False)
                ready = response.status_code == 200
            except httpx.HTTPError:
                pass
            if ready:
                break
            time.sleep(.5)
        if not ready:
            raise RuntimeError("Backend startup timed out")
        asyncio.run(exercise(directory, cfg, children[-1].pid))
    finally:
        for child in reversed(children):
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        # Only ephemeral benchmark credentials were created.
        (directory / "credentials.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
