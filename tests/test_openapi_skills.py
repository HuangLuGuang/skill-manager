import hashlib
import io
import json
import zipfile

import pytest
from fastapi import HTTPException

from agent_manager.api import router as native
from agent_manager.core.manager import AgentManager
from agent_manager.core.policy import CompanyPolicy
from backend.api_errors import http_error_handler
from backend.external_access_models import ExternalSkillScan, ExternalResultEvent
from backend.routers import openapi_skills
from backend.services import openapi_skills as service
from tests.test_external_access import setup, partner, token, bearer


class Queue:
    def __init__(self):
        self.jobs = []

    def submit(self, callback, *args):
        self.jobs.append((callback, args))

    def finish(self):
        while self.jobs:
            callback, args = self.jobs.pop(0)
            callback(*args)


@pytest.fixture
def api(setup, tmp_path, monkeypatch):
    client, sessions = setup
    manager = AgentManager(policy=CompanyPolicy({"require_sandbox_for_risk": []}), data_dir=tmp_path / "registry")
    client.app.include_router(openapi_skills.router)
    client.app.add_exception_handler(HTTPException, http_error_handler)
    client.app.dependency_overrides[native.get_manager] = lambda: manager
    queue = Queue()
    monkeypatch.setattr(native, "_scan_executor", queue)
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {"findings": [], "max_severity": "SAFE"})
    config = tmp_path / "openapi.json"
    config.write_text(json.dumps({
        "profiles": {"standard": {"version": "1", "platform_ids": ["partner", "second"], "use_sandbox": False,
                                    "malicious_rule_ids": ["confirmed-exfiltration"]}},
        "callbacks": {"result": {"version": "1", "platform_ids": ["partner", "second"]}},
    }))
    monkeypatch.setenv("OPENAPI_SKILL_CONFIG", str(config))
    partner(client)
    issued = token(client, scopes=["openapi:skill-submit", "openapi:skill-read"])
    yield client, sessions, manager, queue, issued, config
    queue.finish()


def archive(files=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as output:
        for name, content in (files or {"SKILL.md": "---\nname: external-skill\ndescription: sample\n---\n"}).items():
            output.writestr(name, content)
    return buffer.getvalue()


def submit(api, *, issued=None, content=None, **metadata):
    client, _, _, _, default, _ = api
    content = content if content is not None else archive()
    body = {"business_request_id": "business-1", "skill_id": "external-id", "skill_version": "v1",
            "department_id": "ops", "profile_id": "standard", "callback_id": "result",
            "file_sha256": hashlib.sha256(content).hexdigest(), **metadata}
    return client.post("/openapi/v1/skill-scans", files={"file": ("skill.zip", content, "application/zip")},
                       data={"metadata": json.dumps(body)}, headers=bearer(issued or default))


def url(response):
    assert response.status_code == 202, response.text
    return "/openapi/v1/skill-scans/" + response.json()["data"]["task_id"]


@pytest.mark.parametrize("upgrade_from_first_batch", [False, True], ids=["fresh", "upgraded"])
def test_end_to_end_progress_snapshot_and_request_links(api, upgrade_from_first_batch):
    client, sessions, mgr, queue, issued, _ = api
    if upgrade_from_first_batch:
        from backend.external_access_models import upgrade_external_access_schema
        from agent_manager.core.registry import Registry
        with sessions() as db:
            engine = db.get_bind()
        with engine.begin() as connection:
            ExternalSkillScan.__table__.drop(connection)
            ExternalResultEvent.__table__.drop(connection)
            connection.exec_driver_sql("DROP INDEX ix_external_api_requests_business_request_id")
            connection.exec_driver_sql("ALTER TABLE external_api_requests DROP COLUMN business_request_id")
        with mgr.registry._connect() as connection:
            connection.execute("DROP TABLE skill_scan_run_reports")
        upgrade_external_access_schema(engine)
        mgr.registry = Registry(data_dir=mgr.registry.data_dir)
    response = submit(api)
    path = url(response)
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.json()["data"]["status"] == "pending"
    with sessions() as db:
        row = db.get(ExternalSkillScan, path.split("/")[-1])
        assert row.trigger_source == "external_api" and row.source_platform_id == "partner"
        assert row.external_skill_id == "external-id" and row.source_token_id == issued["record"]["id"]
        version_id, run_id = row.version_id, row.scan_run_id
    headers = bearer(issued)
    pending = client.get(path, headers=headers).json()["data"]
    assert pending["status"] == "pending" and pending["result_ready"] is False
    for suffix in ("/result", "/findings"):
        result = client.get(path + suffix, headers=headers)
        assert result.status_code == 409 and result.json()["error"]["code"] == "RESULT_NOT_READY"
    mgr.registry.update_scan_progress(run_id, "analyzers")
    mgr.registry.update_scan_analyzer(run_id, "scanner", "running")
    assert client.get(path, headers=headers).json()["data"]["progress"]["stage"] == "analyzing"
    queue.finish()
    result = client.get(path + "/result", headers=headers).json()["data"]
    assert result["risk_level"] == "benign" and result["coverage"] == "complete"
    assert result["profile_version"] == "1" and result["skill_id"] == "external-id"
    assert result["finding_counts"] == dict.fromkeys(service.SEVERITIES, 0)
    assert result["completed_at"].endswith("Z")
    progress = client.get(path, headers=headers).json()["data"]
    assert progress["status"] == "succeeded" and progress["result_ready"]
    assert progress["callback"]["attempts"] == 0
    assert client.get(path + "/findings", headers=headers).json()["data"] == {"items": [], "next_cursor": None}
    record = client.get("/api/v1/external-access/requests/" + response.headers["x-request-id"]).json()
    assert record["resource_id"] == version_id and record["business_request_id"] == "business-1"
    assert record["department_id"] == "ops" and record["status_code"] == 202
    assert mgr.registry.get_scan_run_report(run_id)["scan_report"]["analyzer_timings"]["scanner"]["status"] == "completed"
    with sessions() as db:
        event = db.query(ExternalResultEvent).filter_by(task_id=result["task_id"]).one()
        payload = json.loads(event.payload_json)
        assert payload["result"]["risk_level"] == result["risk_level"]
        assert payload["result"]["report_id"] == result["report_id"]
        assert event.status == "pending" and event.attempts == 0


def test_authorization_rotation_and_shared_native_content(api):
    client, sessions, _, queue, issued, _ = api
    response = submit(api)
    path = url(response)
    queue.finish()
    partner(client, "second", 2)
    other = token(client, "second", scopes=["openapi:skill-submit", "openapi:skill-read"])
    for suffix in ("", "/result", "/findings"):
        assert client.get(path + suffix, headers=bearer(other)).status_code == 404
    other_response = submit(api, issued=other)
    other_path = url(other_response)
    queue.finish()
    assert client.get(other_path + "/result", headers=bearer(other)).status_code == 200
    from datetime import datetime
    reused_report = client.get(other_path + "/result", headers=bearer(other)).json()["data"]
    assert datetime.fromisoformat(reused_report["completed_at"]) >= datetime.fromisoformat(other_response.json()["data"]["created_at"])
    with sessions() as db:
        rows = db.query(ExternalSkillScan).all()
        assert rows[0].version_id == rows[1].version_id
        assert rows[0].task_id != rows[1].task_id
    assert submit(api, department_id="unassigned").status_code == 403
    no_read = token(client, scopes=["openapi:skill-submit"])
    assert client.get(path, headers=bearer(no_read)).status_code == 403
    no_submit = token(client, scopes=["openapi:skill-read"])
    assert submit(api, issued=no_submit).status_code == 403
    replacement = token(client, scopes=["openapi:skill-read"])
    client.post(f"/api/v1/access/tokens/{issued['record']['id']}/revoke")
    assert client.get(path, headers=bearer(issued)).status_code == 401
    assert client.get(path + "/result", headers=bearer(replacement)).status_code == 200
    client.put("/api/v1/external-access/platforms/partner", json={"name": "Partner", "departments": [
        {"department_id": "ops", "group_id": 1}, {"department_id": "other", "group_id": 2}]})
    other_department = token(client, scopes=["openapi:skill-read"], allowed_department_ids=["other"])
    for suffix in ("", "/result", "/findings"):
        assert client.get(path + suffix, headers=bearer(other_department)).status_code == 403


def test_findings_pagination_redaction_and_immutable_report(api, monkeypatch):
    client, sessions, mgr, queue, issued, config = api
    findings = [{"rule_id": "confirmed-exfiltration", "severity": "HIGH", "title": "Data transfer",
                 "file_path": "scripts/run.py", "line_number": 3, "code_snippet": "api_key=secret-value",
                 "description": "Evidence", "remediation": "Remove transfer"},
                {"rule": "weak-config", "severity": "LOW", "title": "Configuration", "message": "Review configuration"}]
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {"findings": findings, "max_severity": "HIGH"})
    path = url(submit(api))
    queue.finish()
    headers = bearer(issued)
    old_report = client.get(path + "/result", headers=headers).json()["data"]
    assert old_report["risk_level"] == "malicious"
    first = client.get(path + "/findings?limit=1", headers=headers).json()["data"]
    assert first["items"][0]["severity"] == "high"
    assert "secret-value" not in json.dumps(first)
    assert first["items"][0]["location"] == {"file": "scripts/run.py", "line": 3}
    last = client.get(path + "/findings", params={"limit": 1, "cursor": first["next_cursor"]}, headers=headers).json()["data"]
    assert last["items"][0]["severity"] == "low" and last["next_cursor"] is None
    for params in ({"cursor": "invalid"}, {"limit": 0}, {"limit": 201}):
        assert client.get(path + "/findings", params=params, headers=headers).status_code == 422
    # Rescan the native version, then change the configured profile version.
    with sessions() as db:
        row = db.get(ExternalSkillScan, path.split("/")[-1])
        version_id = row.version_id
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {"findings": [], "max_severity": "SAFE"})
    mgr.request_rescan(version_id)
    mgr.process_pending_submission(version_id, force_scan=True)
    value = json.loads(config.read_text())
    value["profiles"]["standard"]["version"] = "2"
    config.write_text(json.dumps(value))
    assert client.get(path + "/result", headers=headers).json()["data"] == old_report
    new_path = url(submit(api, business_request_id="new"))
    queue.finish()
    assert client.get(new_path + "/result", headers=headers).json()["data"]["profile_version"] == "2"
    assert client.get(new_path + "/findings", params={"cursor": first["next_cursor"]}, headers=headers).status_code == 422


@pytest.mark.parametrize("change", [{"file_sha256": "0" * 64}, {"skill_id": ""}, {"skill_version": "x" * 129}, {"unexpected": "private-input"}])
def test_metadata_validation(api, change):
    response = submit(api, **change)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert "private-input" not in response.text


@pytest.mark.parametrize("content", [b"not-a-zip", archive({"wrapped/SKILL.md": "name: sample"}), archive({"../SKILL.md": "name: sample"})])
def test_invalid_archives_do_not_create_tasks(api, content):
    _, sessions, _, queue, _, _ = api
    assert submit(api, content=content).status_code in (400, 422)
    with sessions() as db:
        assert db.query(ExternalSkillScan).count() == 0
    assert queue.jobs == []


def test_profile_and_upload_limits(api):
    client, _, _, queue, _, config = api
    assert submit(api, profile_id="unknown").status_code == 404
    assert submit(api, callback_id="unknown").status_code == 404
    small = token(client, scopes=["openapi:skill-submit"], max_upload_mb=1, max_concurrent_jobs=1)
    assert submit(api, issued=small, content=b"x" * (1024 * 1024 + 1)).status_code == 413
    url(submit(api, issued=small))
    limited = submit(api, issued=small)
    assert limited.status_code == 429 and limited.headers["retry-after"] == "5"
    queue.finish()
    assert submit(api, issued=small).status_code == 202
    value = json.loads(config.read_text())
    value["profiles"]["standard"]["platform_ids"] = ["second"]
    config.write_text(json.dumps(value))
    assert submit(api).status_code == 403


def test_failed_rescan_never_exposes_previous_success(api, monkeypatch):
    client, _, mgr, queue, issued, config = api
    first = url(submit(api))
    queue.finish()
    first_report = client.get(first + "/result", headers=bearer(issued)).json()["data"]
    value = json.loads(config.read_text())
    value["profiles"]["standard"]["use_behavioral"] = True
    config.write_text(json.dumps(value))
    def fail(*args, **kwargs):
        raise RuntimeError("secret-token-in-upstream-error")
    monkeypatch.setattr("agent_manager.core.vetting.VettingPipeline.vet", fail)
    second = url(submit(api))
    queue.finish()
    progress = client.get(second, headers=bearer(issued)).json()["data"]
    assert progress["status"] == "failed" and progress["result_ready"] is False
    assert "secret-token" not in json.dumps(progress)
    assert client.get(second + "/result", headers=bearer(issued)).json()["error"]["code"] == "REPORT_UNAVAILABLE"
    assert client.get(first + "/result", headers=bearer(issued)).json()["data"] == first_report


def test_missing_scanner_has_no_safe_result(api, monkeypatch):
    client, _, _, queue, issued, _ = api
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {"scanner_unavailable": True})
    path = url(submit(api))
    queue.finish()
    result = client.get(path + "/result", headers=bearer(issued)).json()["data"]
    assert result["risk_level"] is None and result["coverage"] == "none"
    assert "scanner:scanner_unavailable" in result["limitations"]


def test_incompatible_running_profile_is_not_reused(api):
    _, _, _, _, _, config = api
    url(submit(api))
    value = json.loads(config.read_text())
    value["profiles"]["standard"]["use_behavioral"] = True
    config.write_text(json.dumps(value))
    response = submit(api)
    assert response.status_code == 503 and response.json()["error"]["retryable"]


def test_restart_recovers_unfinished_scan_after_lease_expiry(api):
    from datetime import datetime, timedelta
    from sqlalchemy import text
    client, sessions, mgr, queue, issued, _ = api
    path = url(submit(api))
    with sessions() as db:
        task = db.get(ExternalSkillScan, path.split("/")[-1])
        run_id = task.scan_run_id
        db.execute(text("UPDATE request_leases SET expires_at = :past"), {"past": datetime.utcnow() - timedelta(minutes=1)})
        db.commit()
    # Simulate the old process exiting before its executor starts.
    queue.jobs.clear()
    service._executions.pop(run_id)
    service.maintain(mgr)
    service.maintain(mgr)
    assert len(queue.jobs) == 1
    queue.finish()
    assert client.get(path + "/result", headers=bearer(issued)).status_code == 200


def test_report_reconciliation_is_atomic_and_restart_safe(api):
    from concurrent.futures import ThreadPoolExecutor
    client, sessions, mgr, queue, issued, _ = api
    path = url(submit(api))
    # Complete the native execution while the external finalizer is offline.
    with sessions() as db:
        task = db.get(ExternalSkillScan, path.split("/")[-1])
        version_id, run_id = task.version_id, task.scan_run_id
    mgr.process_pending_submission(version_id)
    # Later rescans change the version report, but the execution snapshot survives.
    mgr.request_rescan(version_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: service.reconcile(mgr), range(2)))
    with sessions() as db:
        row = db.get(ExternalSkillScan, path.split("/")[-1])
        assert row.status == "succeeded" and row.scan_run_id == run_id
        assert db.query(ExternalResultEvent).filter_by(task_id=row.task_id).count() == 1
    assert client.get(path + "/result", headers=bearer(issued)).json()["data"]["risk_level"] == "benign"
    queue.finish()


def test_unknown_severity_reports_mapping_failure(api, monkeypatch):
    client, _, _, queue, issued, _ = api
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {
        "findings": [{"severity": "UNRECOGNIZED", "title": "Unmapped"}], "max_severity": "SAFE"})
    path = url(submit(api))
    queue.finish()
    result = client.get(path, headers=bearer(issued)).json()["data"]
    assert result["result_ready"] is False and result["error"]["code"] == "REPORT_UNAVAILABLE"


def test_cancelled_scan_has_terminal_event_without_report(api):
    client, sessions, mgr, queue, issued, _ = api
    path = url(submit(api))
    with sessions() as db:
        row = db.get(ExternalSkillScan, path.split("/")[-1])
        mgr.cancel_scan(row.version_id, reviewer="admin")
    queue.finish()
    state = client.get(path, headers=bearer(issued)).json()["data"]
    assert state["status"] == "cancelled" and state["result_ready"] is False
    assert client.get(path + "/result", headers=bearer(issued)).status_code == 409
    with sessions() as db:
        event = db.query(ExternalResultEvent).filter_by(task_id=state["task_id"]).one()
        assert json.loads(event.payload_json)["result"] is None


def test_deleting_native_skill_keeps_published_external_report(api):
    client, sessions, mgr, queue, issued, _ = api
    path = url(submit(api))
    queue.finish()
    before = client.get(path + "/result", headers=bearer(issued)).json()["data"]
    with sessions() as db:
        row = db.get(ExternalSkillScan, before["task_id"])
        mgr.registry.delete(row.version_id)
        assert mgr.registry.get_scan_run_report(row.scan_run_id) is None
    assert client.get(path + "/result", headers=bearer(issued)).json()["data"] == before
