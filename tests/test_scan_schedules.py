import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from backend import models
from backend.routers import scan_schedules
from backend.scan_schedule_models import SecurityScanSchedule as Schedule
from backend.scan_schedule_models import SecurityScanScheduleRun as Run
from backend.scan_schedule_schemas import ScanTiming
from backend.security_scan_controls import protect_secret
from backend.services import scan_schedules as scheduler
from backend.services import task_risk
from tests.test_agent_security_p1 import _create_policy, _create_target, p1_api  # noqa: F401
from tests.test_asset_lifecycle import scan

ROOT = "/api/v1/agent-security"


@pytest.fixture()
def scheduled(p1_api):  # noqa: F811
    client, factory, state, users = p1_api
    client.app.include_router(scan_schedules.router, prefix="/api")
    target, policy = _create_target(client), _create_policy(client)
    body = {
        "name": "Daily scan",
        "task": {
            "target_id": target["target_id"],
            "policy_id": policy["policy_id"],
            "scan_kind": "control_plane_validation",
        },
        "timing": {"kind": "daily", "timezone": "Asia/Shanghai", "time": "02:00"},
        "idempotency_key": "test-create-schedule",
    }
    return client, factory, state, users, body


def test_schedule_create_acl_update_and_history(scheduled):
    client, factory, state, users, body = scheduled
    first = client.post(f"{ROOT}/scan-schedules", json=body)
    assert first.status_code == 200, first.text
    plan = first.json()
    assert client.post(f"{ROOT}/scan-schedules", json=body).json()["schedule_id"] == plan["schedule_id"]
    state["user"] = users["other"]
    assert client.get(f"{ROOT}/scan-schedules").json() == []
    assert client.post(f"{ROOT}/scan-schedules", json=body).status_code == 403
    state["user"] = users["admin"]
    update = {"name": "Renamed", "timing": plan["timing"], "enabled": False, "version": 1}
    assert client.put(f"{ROOT}/scan-schedules/{plan['schedule_id']}", json=update).status_code == 200
    assert client.put(f"{ROOT}/scan-schedules/{plan['schedule_id']}", json=update).status_code == 409
    run = client.post(f"{ROOT}/scan-schedules/{plan['schedule_id']}/runs", json={"idempotency_key": "manual-1"}).json()
    scheduler.process_run(run["run_id"], factory)
    history = client.get(f"{ROOT}/scan-schedules/{plan['schedule_id']}/runs").json()
    assert history[0]["task_id"], history
    task_id = history[0]["task_id"]
    detail = client.get(f"{ROOT}/tasks/{task_id}").json()
    assert detail["origins"][0]["schedule_id"] == plan["schedule_id"]
    assert client.delete(f"{ROOT}/scan-schedules/{plan['schedule_id']}").status_code == 200
    assert client.get(f"{ROOT}/tasks/{task_id}").status_code == 200
    assert client.get(f"{ROOT}/scan-schedules").json() == []
    listed = client.get(f"{ROOT}/tasks").json()
    listed_task = next(item for item in listed if item['task_id'] == task_id)
    assert listed_task['origins'] == [{"kind": "scheduled", "schedule_id": plan['schedule_id'], "name": "Renamed", "deleted": True}]


def test_double_dispatch_coalesces_missed_periods_and_skips_overlap(scheduled):
    client, factory, _, _, body = scheduled
    plan = client.post(f"{ROOT}/scan-schedules", json=body).json()
    now = datetime(2026, 9, 9, 0, 0)
    with factory() as db:
        db.get(Schedule, plan["schedule_id"]).next_run_at = now - timedelta(days=3)
        db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: scheduler.dispatch_due(factory, now), range(2)))
    with factory() as db:
        assert db.query(Run).count() == 1
        run = db.query(Run).one()
        run_id = run.run_id
        assert db.get(Schedule, plan["schedule_id"]).next_run_at > now
    scheduler.process_run(run_id, factory)
    scheduler.process_run(run_id, factory)
    with factory() as db:
        assert db.query(models.SecurityScanTask).count() == 1
    result = client.post(
        f"{ROOT}/scan-schedules/{plan['schedule_id']}/runs", json={"idempotency_key": "manual-overlap"}
    ).json()
    assert result["status"] == "skipped"
    assert result["error_code"] == "scan_schedule.previous_running"


def test_disabled_actor_fails_and_paused_queued_run_cancels(scheduled):
    client, factory, _, _, body = scheduled
    body["run_immediately"] = True
    plan = client.post(f"{ROOT}/scan-schedules", json=body).json()
    run_id = plan["last_run"]["run_id"]
    with factory() as db:
        db.query(models.User).filter_by(username="admin").one().is_active = False
        db.commit()
    scheduler.process_run(run_id, factory)
    with factory() as db:
        assert db.get(Run, run_id).error_code == "scan_schedule.actor_unavailable"
        row = db.get(Schedule, plan["schedule_id"])
        new = scheduler.queue_run(db, row, "next", "scheduled")
        row.enabled = False
        db.commit()
        next_id = new.run_id
    scheduler.process_run(next_id, factory)
    with factory() as db:
        assert db.get(Run, next_id).status == "cancelled"
        assert db.query(models.SecurityScanTask).count() == 0


def test_weekly_timezone_and_invalid_input():
    timing = ScanTiming(kind="weekly", weekday=1, time="02:00", timezone="Asia/Shanghai")
    assert scheduler.next_due(timing, datetime(2026, 9, 8)) == datetime(2026, 9, 13, 18)
    with pytest.raises(ValueError):
        ScanTiming(timezone="not-a-zone")
    with pytest.raises(ValueError):
        ScanTiming(kind="cron", cron="* * * * * *")


def test_task_score_is_frozen_and_missing_rules_not_zero(scheduled):
    client, factory, _, _, body = scheduled
    with factory() as db:
        from backend.services.agent_risk import managed_agent

        agent = managed_agent(db, body["task"]["target_id"])
        task = scan(db, agent, body["task"]["policy_id"], finding=True)
        task.scan_options_encrypted = protect_secret(json.dumps({"skills": ["data-leakage-detection"]}))
        db.flush()
        original = task_risk.report_score(db, task)
        assert original["score"] == 65 and original["status"] == "complete"
        db.commit()
        finding = db.query(models.SecurityFinding).filter_by(task_id=task.task_id).one()
        finding.status, finding.severity = "false_positive", "low"
        db.commit()
        assert task_risk.report_score(db, task) == original
        second = scan(db, agent, body["task"]["policy_id"])
        second.scan_options_encrypted = protect_secret(
            json.dumps({"skills": ["data-leakage-detection", "tool-abuse-detection"]})
        )
        db.flush()
        score = task_risk.report_score(db, second)
        assert score["score"] is None and score["status"] == "partial"
        assert score["total_checks"] == 2


def test_automatic_triggers_share_active_task_and_recover_after_dispatch(scheduled):
    client, factory, _, _, body = scheduled
    base = body['task']
    first = client.post(f'{ROOT}/tasks', json={**base, 'idempotency_key': 'schedule:first-test'})
    assert first.status_code == 200, first.text
    second = client.post(f'{ROOT}/tasks', json={**base, 'idempotency_key': 'asset-change:agent:1'})
    assert second.status_code == 200, second.text
    assert second.json()['task_id'] == first.json()['task_id']
    # The durable trigger alias survives completion and makes retries idempotent.
    with factory() as db:
        task = db.query(models.SecurityScanTask).one()
        task.status = 'succeeded'
        db.commit()
    replay = client.post(f'{ROOT}/tasks', json={**base, 'idempotency_key': 'asset-change:agent:1'})
    assert replay.json()['task_id'] == first.json()['task_id']
    later = client.post(f'{ROOT}/tasks', json={**base, 'idempotency_key': 'schedule:later-test'})
    assert later.status_code == 200, later.text
    assert later.json()['task_id'] != first.json()['task_id']


def test_schedule_freezes_occurrence_config_and_records_approval_failure(scheduled, monkeypatch):
    from backend.api_errors import ApiError
    from backend.routers import security_scans
    from backend.security_scan_controls import unprotect_secret
    client, factory, _, _, body = scheduled
    body['run_immediately'] = True
    plan = client.post(f'{ROOT}/scan-schedules', json=body).json()
    run_id = plan['last_run']['run_id']
    with factory() as db:
        row = db.get(Schedule, plan['schedule_id'])
        row.task_json = protect_secret(json.dumps({**body['task'], 'prompt': 'future configuration'}))
        db.commit()
        assert 'future configuration' not in unprotect_secret(db.get(Run, run_id).task_json)
    async def requires_approval(*args, **kwargs):
        raise ApiError(409, 'agent_security.production_active_safe_approval_required', '需要审批', 'Approval required')
    monkeypatch.setattr(security_scans, 'create_task', requires_approval)
    scheduler.process_run(run_id, factory)
    with factory() as db:
        run = db.get(Run, run_id)
        assert run.status == 'awaiting_approval'
        assert run.task_id is None
        assert db.query(models.SecurityScanTask).count() == 0


def test_target_profile_links_plan_and_current_risk(scheduled):
    from backend.routers import asset_lifecycle
    client, _, _, _, body = scheduled
    client.app.include_router(asset_lifecycle.router, prefix='/api')
    plan = client.post(f'{ROOT}/scan-schedules', json=body).json()
    profile = client.get(f"{ROOT}/targets/{body['task']['target_id']}/risk-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()['schedules'][0]['schedule_id'] == plan['schedule_id']
    assert profile.json()['risk']['score'] is None


def test_pdf_includes_task_score_and_coverage():
    from io import BytesIO

    from pypdf import PdfReader

    from backend.security_scan_pdf import build_security_scan_pdf
    detail = {'task': {'task_id': 'task', 'status': 'succeeded', 'scan_kind': 'agent_risk_scan'},
              'risk_score': {'score': 65, 'completed_checks': 1, 'total_checks': 2}}
    document = build_security_scan_pdf(detail, language='en-US')
    text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(document)).pages)
    assert '65 / 100' in text and 'Check coverage: 1 / 2' in text


def test_terminal_counts_and_scheduled_finding_provenance(scheduled):
    client, factory, _, _, body = scheduled
    body['run_immediately'] = True
    plan = client.post(f'{ROOT}/scan-schedules', json=body).json()
    scheduler.process_run(plan['last_run']['run_id'], factory)
    task_id = client.get(f"{ROOT}/scan-schedules/{plan['schedule_id']}/runs").json()[0]['task_id']
    with factory() as db:
        task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
        task.scan_kind = 'llm_redteam_scan'
        task.status = 'succeeded'
        task.scan_options_encrypted = protect_secret(json.dumps({
            'datasets': ['a', 'b'], 'num_prompts': 10, 'techniques': ['Raw'],
            'planned_prompt_count': 20, 'live_progress': {'completed': 10},
        }))
        for index in range(20):
            db.add(models.SecurityScanCase(case_id=f'coverage-{index}', task_id=task_id,
                external_case_id=f'aig-llm-prompt:{index}', category='llm_redteam_prompt',
                title='Test case', status='passed', round_count=1))
        db.add(models.SecurityFinding(finding_id='scheduled-finding', task_id=task_id,
            finding_code='test', severity='high', status='open', title='Test finding',
            description='Evidence', source='test'))
        db.commit()
    item = next(item for item in client.get(f'{ROOT}/tasks').json() if item['task_id'] == task_id)
    assert item['progress']['completed'] == item['progress']['planned'] == 20
    detail = client.get(f'{ROOT}/tasks/{task_id}').json()
    assert detail['task']['progress']['completed'] == len(detail['cases']) == 20
    finding = client.get(f'{ROOT}/findings').json()['items'][0]
    assert finding['origins'] == item['origins']
    assert finding['origins'][0]['kind'] == 'scheduled'
