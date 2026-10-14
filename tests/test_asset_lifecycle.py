import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent_manager.core.dify_console_client import DifyConsoleClient, DifyConsoleError
from backend import models
from backend.asset_lifecycle_schemas import SourceConfig
from backend.routers import asset_lifecycle, security_scans
from backend.security_scan_controls import json_dumps, new_resource_id, unprotect_secret
from backend.services import agent_risk, asset_sync
from backend.services.dify_inventory import persist_inventory_snapshot
from tests.test_agent_security_p1 import _create_policy, _create_target, p1_api  # noqa: F401

ROOT = "/api/v1/agent-security"


def add_evaluator(factory):
    with factory() as db:
        provider = models.ModelProvider(name="asset-judge-provider", base_url="https://judge.example/v1")
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(provider_id=provider.id, name="asset-judge"))
        db.commit()


@pytest.fixture()
def lifecycle(p1_api):  # noqa: F811
    client, factory, state, users = p1_api
    client.app.include_router(asset_lifecycle.router, prefix="/api")
    target = _create_target(
        client,
        target_type="dify",
        config={
            "app_id": "app-1",
            "workspace_id": "workspace-1",
            "console_base_url": "https://8.8.8.8",
        },
    )
    response = client.post(
        f"{ROOT}/targets/{target['target_id']}/credentials",
        json={"purpose": "dify_console_api", "secret": "test-console-secret"},
    )
    assert response.status_code == 200, response.text
    policy = _create_policy(client, execution_mode="read_only")
    body = {
        "name": "Workspace",
        "template_target_id": target["target_id"],
        "policy_id": policy["policy_id"],
        "config": {"app_ids": ["app-1"], "skills": ["data-leakage-detection"]},
    }
    created = client.post(f"{ROOT}/asset-sources", json=body)
    assert created.status_code == 200, created.text
    return client, factory, state, users, target, policy, created.json(), body


def inventory(db, target_id, policy_id, *, fingerprint="prompt-a", created_at=None):
    now = created_at or datetime.utcnow()
    task = models.SecurityScanTask(
        task_id=new_resource_id("test"),
        target_id=target_id,
        policy_id=policy_id,
        scan_kind="dify_asset_inventory",
        status="succeeded",
        idempotency_key=new_resource_id("idem"),
        request_fingerprint="x",
        created_by="admin",
        timeout_at=now + timedelta(hours=1),
        created_at=now,
        completed_at=now,
    )
    db.add(task)
    db.flush()
    agent_risk.bind_scan(db, task, {})
    report = {
        "schema_version": "dify-asset-inventory@1",
        "engine_name": "agent-manager-dify-inventory",
        "agent_profile": {"app_id": {"value": "app-1"}},
        "summary": {"mcp": 0, "knowledge_bases": 0},
        "coverage": {"dsl": "completed", "dify_console_api": "completed"},
        "prompts": [
            {
                "asset_id": "prompt:p1",
                "asset_type": "prompt",
                "name": "system",
                "verification_status": "verified",
                "details": {"sha256": fingerprint},
                "sources": [],
            }
        ],
    }
    snapshot = persist_inventory_snapshot(db, task, report)
    agent_risk.record_inventory(db, task, report, snapshot.snapshot_id)
    db.flush()
    return task, agent_risk.managed_agent(db, target_id)


def scan(db, agent, policy_id, *, finding=False, status="succeeded", key="prompt-leak", created_at=None):
    now = created_at or datetime.utcnow()
    task = models.SecurityScanTask(
        task_id=new_resource_id("test"),
        target_id=agent.target_id,
        policy_id=policy_id,
        scan_kind="agent_risk_scan",
        status=status,
        idempotency_key=new_resource_id("idem"),
        request_fingerprint="x",
        created_by="admin",
        timeout_at=now + timedelta(hours=1),
        created_at=now,
        completed_at=now,
        engine_version="v1",
    )
    db.add(task)
    db.flush()
    agent_risk.bind_scan(db, task, {"skills": ["data-leakage-detection"]})
    case = models.SecurityScanCase(
        case_id=new_resource_id("case"),
        task_id=task.task_id,
        external_case_id="aig-rule:data-leakage-detection",
        category="agent_detection_skill",
        title="test",
        round_count=1,
        response_summary_json='{"execution_status":"completed","dialogue_calls":1}',
        status="failed" if finding else "passed",
    )
    db.add(case)
    db.flush()
    if finding:
        db.add(
            models.SecurityFinding(
                finding_id=new_resource_id("find"),
                task_id=task.task_id,
                case_id=case.case_id,
                asset_id="prompt:p1",
                finding_code=key,
                severity="high",
                status="open",
                title=new_resource_id("changing-title"),
                description="Evidence",
                evidence_json='{"location":"prompt:p1"}',
                source="test",
                created_at=now,
            )
        )
    db.flush()
    return task


def test_source_validation_idempotency_and_authorization(lifecycle):
    client, _, state, users, _, _, source, body = lifecycle
    assert client.post(f"{ROOT}/asset-sources", json=body).json()["source_id"] == source["source_id"]
    state["user"] = users["other"]
    assert client.get(f"{ROOT}/asset-sources").json() == []
    assert (
        client.post(f"{ROOT}/asset-sources/{source['source_id']}/sync-runs", json={"idempotency_key": "x"}).status_code
        == 403
    )
    assert client.get(f"{ROOT}/managed-agents").json()["total"] == 0
    state["user"] = users["auditor"]
    assert len(client.get(f"{ROOT}/asset-sources").json()) == 1
    assert client.post(f"{ROOT}/asset-sources", json=body).status_code == 403


def test_schedule_timezone_anchor_and_invalid_input():
    config = SourceConfig(app_ids=["a"], schedule_kind="daily", daily_time="02:00")
    assert asset_sync.next_due(config, datetime(2026, 9, 8, 17)) == datetime(2026, 9, 8, 18)
    config = SourceConfig(app_ids=["a"], interval_minutes=60)
    assert asset_sync.next_due(config, datetime(2026, 9, 8, 3, 25), anchor=datetime(2026, 9, 8)) == datetime(
        2026, 9, 8, 4
    )
    for values in (
        {"timezone": "not-a-zone"},
        {"scope": "selected", "app_ids": []},
        {"schedule_kind": "cron", "cron": "* * bad"},
    ):
        with pytest.raises(ValidationError):
            SourceConfig(**{"app_ids": ["a"], **values})


def test_dispatch_claims_once_and_coalesces_missed_runs(lifecycle):
    _, factory, _, _, _, _, source, _ = lifecycle
    now = datetime.utcnow()
    with factory() as db:
        db.get(models.AssetSource, source["source_id"]).next_run_at = now - timedelta(days=5)
        db.commit()

    def dispatch():
        with factory() as db:
            return asset_sync.dispatch_due(db, now)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: dispatch(), range(2)))
    with factory() as db:
        assert db.query(models.AssetSyncRun).count() == 1
        assert db.get(models.AssetSource, source["source_id"]).next_run_at > now


def test_sync_resumes_existing_child_and_does_not_duplicate(lifecycle, monkeypatch):
    client, factory, _, _, target, policy, source, _ = lifecycle
    monkeypatch.setattr(asset_sync, "discovery_client", lambda *_: SimpleNamespace())
    response = client.post(f"{ROOT}/asset-sources/{source['source_id']}/sync-runs", json={"idempotency_key": "one"})
    run_id = response.json()["run_id"]
    assert (
        client.post(f"{ROOT}/asset-sources/{source['source_id']}/sync-runs", json={"idempotency_key": "one"}).json()[
            "run_id"
        ]
        == run_id
    )
    assert (
        client.post(
            f"{ROOT}/asset-sources/{source['source_id']}/sync-runs", json={"idempotency_key": "two"}
        ).status_code
        == 409
    )
    asset_sync.process_run(run_id, factory)
    asset_sync.process_run(run_id, factory)
    with factory() as db:
        assert db.query(models.AssetSyncRunItem).count() == 1
        item = db.query(models.AssetSyncRunItem).one()
        assert item.task_id
        assert db.query(models.SecurityScanTask).count() == 1
        task = db.query(models.SecurityScanTask).filter_by(task_id=item.task_id).one()
        task.status, task.completed_at = "succeeded", datetime.utcnow()
        _, agent = inventory(db, target["target_id"], policy["policy_id"])
        db.commit()
    asset_sync.process_run(run_id, factory)
    detail = client.get(f"{ROOT}/asset-sync-runs/{run_id}").json()
    assert detail["status"] == "succeeded", detail
    assert detail["items"][0]["change_kind"] == "added"
    assert client.get(f"{ROOT}/asset-sources").json()[0]["last_success_at"]


def test_cancel_pending_run_does_not_create_inventory_task(lifecycle, monkeypatch):
    client, factory, _, _, _, _, source, _ = lifecycle
    run_id = client.post(
        f"{ROOT}/asset-sources/{source['source_id']}/sync-runs", json={"idempotency_key": "cancel"}
    ).json()["run_id"]
    assert client.post(f"{ROOT}/asset-sync-runs/{run_id}/cancel").status_code == 200
    asset_sync.process_run(run_id, factory)
    with factory() as db:
        assert db.get(models.AssetSyncRun, run_id).status == "cancelled"
        assert db.query(models.SecurityScanTask).count() == 0


def test_workspace_failure_preserves_observed_assets(lifecycle, monkeypatch):
    client, factory, _, _, target, _, source, _ = lifecycle
    with factory() as db:
        row = db.get(models.AssetSource, source["source_id"])
        config = json.loads(row.config_json)
        config["scope"] = "workspace"
        row.config_json = json_dumps(config)
        agent = agent_risk.managed_agent(db, target["target_id"])
        agent.source_id = row.source_id
        db.commit()

    def fail():
        raise DifyConsoleError("dify_inventory.console_forbidden")

    monkeypatch.setattr(asset_sync, "discovery_client", lambda *_: SimpleNamespace(list_apps=fail))
    run_id = client.post(
        f"{ROOT}/asset-sources/{source['source_id']}/sync-runs", json={"idempotency_key": "fail"}
    ).json()["run_id"]
    asset_sync.process_run(run_id, factory)
    with factory() as db:
        assert db.query(models.SecurityAgentAsset).one().observation_status == "observed"
        assert db.get(models.AssetSyncRun, run_id).enumeration_complete is False
        assert db.get(models.AssetSyncRun, run_id).status == "failed"


def test_scoring_dedup_staleness_and_failed_scan_retains_risk(lifecycle):
    client, factory, _, _, target, policy, source, _ = lifecycle
    with factory() as db:
        _, agent = inventory(db, target["target_id"], policy["policy_id"])
        agent.source_id = source["source_id"]
        first = scan(db, agent, policy["policy_id"], finding=True)
        scan(db, agent, policy["policy_id"], finding=True, created_at=first.created_at + timedelta(seconds=1))
        risk = agent_risk.calculate(db, agent)
        assert risk["score"] == 65 and risk["issue_count"] == 1
        assert risk["status"] == "complete"
        inventory(db, target["target_id"], policy["policy_id"], fingerprint="changed")
        risk = agent_risk.calculate(db, agent)
        assert risk["score"] == 65 and risk["status"] == "stale"
        scan(db, agent, policy["policy_id"], status="failed", created_at=first.created_at + timedelta(seconds=2))
        assert agent_risk.calculate(db, agent)["score"] == 65
        db.commit()
    response = client.get(f"{ROOT}/managed-agents")
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["risk"]["score"] == 65


def test_unassessed_is_null_and_closure_requires_comparable_evidence(lifecycle):
    client, factory, _, _, target, policy, source, _ = lifecycle
    assert client.get(f"{ROOT}/managed-agents").json()["items"][0]["risk"]["score"] is None
    with factory() as db:
        _, agent = inventory(db, target["target_id"], policy["policy_id"])
        agent.source_id = source["source_id"]
        scan(db, agent, policy["policy_id"], finding=True)
        risk = agent_risk.calculate(db, agent)
        issue_id, agent_id = risk["contributions"][0]["issue_id"], agent.agent_id
        clean = scan(db, agent, policy["policy_id"])
        clean_id = clean.task_id
        db.commit()
    path = f"{ROOT}/managed-agents/{agent_id}/risk-issues/{issue_id}"
    assert client.patch(path, json={"status": "resolved", "comment": "fixed"}).status_code == 409
    assert client.patch(path, json={"status": "accepted", "comment": "accepted"}).status_code == 200
    assert client.get(f"{ROOT}/managed-agents/{agent_id}/risk").json()["score"] == 65
    assert (
        client.patch(
            path, json={"status": "resolved", "comment": "rescan checked", "closure_task_id": clean_id}
        ).status_code
        == 200
    )
    assert client.get(f"{ROOT}/managed-agents/{agent_id}/risk").json()["score"] == 0


def test_pagination_rejects_truncation_and_repeated_pages():
    client = object.__new__(DifyConsoleClient)
    client._request_json = lambda *a, **kw: {"data": [{"id": "a", "name": "Agent"}], "has_more": True}
    with pytest.raises(DifyConsoleError, match="pagination_invalid"):
        client.list_apps()
    client._request_json = lambda *a, **kw: {"data": [{"id": "a"}, {"id": "b"}], "has_more": False}
    with pytest.raises(DifyConsoleError, match="scope_limit_exceeded"):
        client.list_apps(max_apps=1)


def test_score_bounds_and_contribution_sum():
    for count in (0, 1, 50):
        score, contributions = agent_risk.score_issues([{"issue_id": str(i), "severity": "low"} for i in range(count)])
        assert score <= 30
        assert sum(x["points"] for x in contributions) == score
    score, contributions = agent_risk.score_issues([{"issue_id": str(i), "severity": "critical"} for i in range(10)])
    assert score == 100 == sum(x["points"] for x in contributions)


def test_late_inventory_cannot_overwrite_newer_configuration(lifecycle):
    _, factory, _, _, target, policy, _, _ = lifecycle
    with factory() as db:
        _, agent = inventory(db, target["target_id"], policy["policy_id"], fingerprint="new")
        fingerprint, snapshot = agent.config_fingerprint, agent.snapshot_id
        inventory(
            db,
            target["target_id"],
            policy["policy_id"],
            fingerprint="old",
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        assert agent.config_fingerprint == fingerprint
        assert agent.snapshot_id == snapshot


def test_configuration_digest_tracks_code_but_ignores_canvas_positions():
    from copy import deepcopy

    from agent_manager.core.dify_inventory.dsl_collector import configuration_digest

    document = {
        "workflow": {
            "graph": {"nodes": [{"id": "code", "position": {"x": 1}, "data": {"type": "code", "code": "return 1"}}]}
        }
    }
    moved = deepcopy(document)
    moved["workflow"]["graph"]["nodes"][0]["position"]["x"] = 50
    assert configuration_digest(document) == configuration_digest(moved)
    moved["workflow"]["graph"]["nodes"][0]["data"]["code"] = "return 2"
    assert configuration_digest(document) != configuration_digest(moved)


def test_discovery_reuses_identity_and_inherits_only_workspace_credentials(lifecycle):
    client, factory, _, _, target, _, source, _ = lifecycle
    client.post(
        f"{ROOT}/targets/{target['target_id']}/credentials", json={"purpose": "dify_app_api", "secret": "app-secret"}
    )
    with factory() as db:
        row = db.get(models.AssetSource, source["source_id"])
        agent = asset_sync._ensure_target(db, row, {"id": "app-2", "name": "Second App"})
        target_id = agent.target_id
        db.commit()
        assert security_scans._active_credential(db, target_id, "dify_app_api") is None
        assert security_scans._active_credential(db, target_id, "dify_console_api").target_id == target["target_id"]
        same = asset_sync._ensure_target(db, row, {"id": "app-2", "name": "Renamed App"})
        assert same.target_id == target_id
        template = db.query(models.SecurityTarget).filter_by(target_id=target["target_id"]).one()
        config = json.loads(template.config_json)
        config["console_base_url"] = "https://1.1.1.1"
        template.config_json = json_dumps(config)
        db.commit()
        assert security_scans._active_credential(db, target_id, "dify_console_api") is None


def test_event_rescan_is_idempotent_and_rule_failure_remains_actionable(lifecycle, monkeypatch):
    _, factory, _, _, target, policy, source, _ = lifecycle
    add_evaluator(factory)
    with factory() as db:
        _, agent = inventory(db, target["target_id"], policy["policy_id"])
        agent.source_id = source["source_id"]
        row = db.get(models.AssetSource, source["source_id"])
        config = json.loads(row.config_json)
        config["auto_scan_policy_id"] = policy["policy_id"]
        config["evaluation_model"] = "asset-judge"
        row.config_json = json_dumps(config)
        db.commit()
    from backend.api_errors import ApiError

    original = security_scans.create_task

    async def denied(*args, **kwargs):
        raise ApiError(409, "agent_security.production_active_safe_approval_required", "需要审批", "Approval required")

    monkeypatch.setattr(security_scans, "create_task", denied)
    asset_sync.process_events(factory)
    with factory() as db:
        event = db.query(models.AssetLifecycleEvent).one()
        assert event.processed_at is None
        assert event.next_attempt_at > datetime.utcnow()
        assert event.error_code == "agent_security.production_active_safe_approval_required"
        event.next_attempt_at = None
        db.commit()
    monkeypatch.setattr(security_scans, "create_task", original)
    asset_sync.process_events(factory)
    asset_sync.process_events(factory)
    with factory() as db:
        task = db.query(models.SecurityScanTask).filter_by(scan_kind="agent_risk_scan").one()
        assert json.loads(unprotect_secret(task.scan_options_encrypted))["evaluation_model"] == "asset-judge"
        event = db.query(models.AssetLifecycleEvent).one()
        assert event.processed_at is not None
        assert event.error_code is None
        assert event.next_attempt_at is None


@pytest.mark.parametrize("model_name, provider_enabled, model_enabled, error", [
    (None, True, True, "agent_security.evaluation_model_required"),
    ("missing-model", True, True, "agent_security.evaluation_model_invalid"),
    ("asset-judge", False, True, "agent_security.evaluation_model_invalid"),
    ("asset-judge", True, False, "agent_security.evaluation_model_invalid"),
    ("asset-judge", True, True, None),
])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_source_auto_scan_validates_evaluator(lifecycle, model_name, provider_enabled, model_enabled, error, operation):
    client, factory, _, _, _, policy, source, body = lifecycle
    add_evaluator(factory)
    with factory() as db:
        db.query(models.ModelProvider).one().enabled = provider_enabled
        db.query(models.ModelEndpoint).one().enabled = model_enabled
        if operation == "create":
            db.delete(db.get(models.AssetSource, source["source_id"]))
        db.commit()
    body["config"].update(auto_scan_policy_id=policy["policy_id"], evaluation_model=model_name)
    if operation == "create":
        response = client.post(f"{ROOT}/asset-sources", json=body)
    else:
        body.pop("template_target_id")
        response = client.put(f"{ROOT}/asset-sources/{source['source_id']}", json={**body, "version": source["version"]})
    assert response.status_code == (422 if error else 200), response.text
    if error:
        assert response.json()["error_code"] == error
    else:
        assert response.json()["config"]["evaluation_model"] == "asset-judge"


@pytest.mark.parametrize("configured", [False, True])
def test_auto_scan_preserves_pending_event_when_evaluator_unavailable(lifecycle, configured):
    _, factory, _, _, target, policy, source, _ = lifecycle
    add_evaluator(factory)
    with factory() as db:
        _, agent = inventory(db, target["target_id"], policy["policy_id"])
        agent.source_id = source["source_id"]
        row = db.get(models.AssetSource, source["source_id"])
        config = json.loads(row.config_json)
        config["auto_scan_policy_id"] = policy["policy_id"]
        if configured:
            config["evaluation_model"] = "asset-judge"
            db.query(models.ModelEndpoint).one().enabled = False
        row.config_json = json_dumps(config)
        db.commit()
    asset_sync.process_events(factory)
    with factory() as db:
        event = db.query(models.AssetLifecycleEvent).one()
        assert event.processed_at is None
        assert event.next_attempt_at > datetime.utcnow()
        assert event.error_code == ("agent_security.evaluation_model_invalid" if configured else "agent_security.evaluation_model_required")
        assert db.query(models.SecurityScanTask).filter_by(scan_kind="agent_risk_scan").count() == 0


def test_shared_mcp_risk_requires_explicit_same_owner_link(lifecycle):
    client, factory, _, users, target, policy, source, _ = lifecycle
    with factory() as db:
        _, agent = inventory(db, target["target_id"], policy["policy_id"])
        agent.source_id = source["source_id"]
        agent_id = agent.agent_id
        mcp = models.SecurityTarget(
            target_id="shared-mcp",
            name="Shared MCP",
            target_type="mcp_gateway",
            connector_type="mcp_gateway",
            asset_type="mcp",
            endpoint_url="mcp-gateway://1",
            created_by="admin",
            owner_user_id=users["admin"].id,
        )
        db.add(mcp)
        db.flush()
        scan(db, SimpleNamespace(target_id=mcp.target_id), policy["policy_id"], finding=True)
        db.commit()
    path = f"{ROOT}/managed-agents/{agent_id}"
    assert client.get(f"{path}/risk").json()["score"] is None
    response = client.put(f"{path}/related-targets", json={"target_ids": ["shared-mcp"]})
    assert response.status_code == 200, response.text
    assert client.get(f"{path}/risk").json()["score"] == 65
    client.put(f"{path}/related-targets", json={"target_ids": []})
    assert client.get(f"{path}/risk").json()["score"] is None
    with factory() as db:
        db.query(models.SecurityTarget).filter_by(target_id="shared-mcp").one().owner_user_id = users["other"].id
        db.commit()
    assert client.put(f"{path}/related-targets", json={"target_ids": ["shared-mcp"]}).status_code == 422
