import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from agent_manager.api import router as native
from backend import auth, iam, models
from backend.config import settings
from backend.external_access_models import ExternalAgentJob, ExternalSkillScan, ExternalResultEvent, ExternalGatewayEvent
from backend.routers import openapi_profiles
from backend.services import openapi_profiles as service, openapi_agents, openapi_skills
from tests.test_external_access import setup, partner
from tests.test_openapi_agents import api as agent_api, register, ready, evaluate, claim, complete, bearer
from tests.test_openapi_skills import api as skill_api, submit, url, archive

ROOT = "/api/v1/external-access/profiles"


@pytest.fixture
def api(setup, tmp_path, monkeypatch):
    client, sessions = setup
    client.app.include_router(openapi_profiles.router, prefix="/api/v1")
    client.app.dependency_overrides[native.get_manager] = lambda: SimpleNamespace(registry=SimpleNamespace(data_dir=tmp_path / "registry"))
    skill_path, agent_path = tmp_path / "skill-config.json", tmp_path / "agent-config.json"
    monkeypatch.setenv("OPENAPI_SKILL_CONFIG", str(skill_path))
    monkeypatch.setenv("OPENAPI_AGENT_CONFIG", str(agent_path))
    partner(client)
    with sessions() as db:
        provider = models.ModelProvider(name="Provider", base_url="http://model.test/v1")
        db.add(provider)
        db.flush()
        db.add(models.ModelEndpoint(name="judge", provider_id=provider.id))
        db.add(models.SecurityScanPolicy(policy_id="policy", name="Policy", created_by="admin", execution_mode="active_safe"))
        db.commit()
    return client, sessions, skill_path, agent_path


def body(client, kind="skill", profile_id="standard", **changes):
    values = {"platform_ids": ["partner"], "malicious_rule_ids": []}
    if kind == "agent":
        values.update(policy_id="policy", evaluation_model="judge", skills=["data-leakage-detection"])
    values.update(changes)
    response = client.get(ROOT + "/" + kind)
    assert response.status_code == 200, response.text
    return {"profile_id": profile_id, "revision": response.json()["revision"], "settings": values}


@pytest.mark.parametrize("kind", ["skill", "agent"])
def test_file_create_edit_read_and_runtime_consumption(api, kind):
    client, _, skill_path, agent_path = api
    path = skill_path if kind == "skill" else agent_path
    initial = {"profiles": {}, "callbacks": {"cb": {"version": "cb-2", "platform_ids": ["partner"]}}}
    if kind == "agent":
        initial.update(partners={"partner": {"allowed_cidrs": ["10.0.0.0/8"], "connection_policy_ids": {"test": "policy"}}},
                       gateways={"gw": {"version": "gw-3", "platform_ids": ["partner"]}})
    path.write_text(json.dumps(initial))
    request = body(client, kind)
    response = client.post(ROOT + "/" + kind, json=request)
    assert response.status_code == 201, response.text
    saved = response.json()["items"][0]
    assert saved["version"].startswith("v_")
    assert saved["platform_ids"] == ["partner"]
    assert client.get(ROOT + "/" + kind).json() == response.json()
    request = body(client, kind, malicious_rule_ids=["confirmed-rule"])
    updated = client.put(ROOT + "/" + kind, json=request)
    assert updated.status_code == 200, updated.text
    new = updated.json()["items"][0]
    assert new["version"] != saved["version"]
    config = json.loads(path.read_text())
    assert {k: v for k, v in config.items() if k != "profiles"} == {k: v for k, v in initial.items() if k != "profiles"}
    if kind == "skill":
        p, cb = openapi_skills.configuration(SimpleNamespace(profile_id="standard", callback_id="cb"), SimpleNamespace(platform_id="partner"), path.parent)
    else:
        p = openapi_agents.configuration().profiles["standard"]
    assert p.version == new["version"] and p.malicious_rule_ids == ["confirmed-rule"]
    before = path.read_bytes()
    request["revision"] = updated.json()["revision"]
    assert client.put(ROOT + "/" + kind, json=request).status_code == 200
    assert path.read_bytes() == before  # No-op saves retain both content and version.


def test_load_defaults_and_paths(api, monkeypatch, tmp_path):
    client, _, skill_path, agent_path = api
    assert client.get(ROOT + "/skill").json()["items"] == []
    assert not skill_path.exists()
    monkeypatch.delenv("OPENAPI_SKILL_CONFIG")
    monkeypatch.delenv("OPENAPI_AGENT_CONFIG")
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "backend"))
    assert service.config_path("skill", tmp_path / "registry") == tmp_path / "registry/openapi-skills.json"
    assert service.config_path("agent", tmp_path) == tmp_path / "backend/openapi-agents.json"
    assert client.post(ROOT + "/skill", json=body(client)).status_code == 201
    assert (tmp_path / "registry/openapi-skills.json").exists()
    assert not agent_path.exists()


def test_existing_versions_and_optional_defaults_are_visible_without_rewrite(api):
    client, _, path, _ = api
    path.write_text(json.dumps({"profiles": {"old": {"version": "release-7", "platform_ids": ["partner"]}}, "callbacks": {}}))
    original = path.read_bytes()
    row = client.get(ROOT + "/skill").json()["items"][0]
    assert row["version"] == "release-7" and row["use_sandbox"] is True and row["use_llm"] is False
    assert path.read_bytes() == original


@pytest.mark.parametrize("kind,changes,code", [
    ("skill", {"use_llm": "false"}, "invalid_fields"),
    ("skill", {"platform_ids": []}, "invalid_fields"),
    ("skill", {"platform_ids": ["partner", "partner"]}, "invalid_fields"),
    ("skill", {"platform_ids": ["unknown"]}, "partner_invalid"),
    ("skill", {"malicious_rule_ids": ["rule", "rule"]}, "invalid_fields"),
    ("skill", {"malicious_rule_ids": [" "]}, "invalid_fields"),
    ("skill", {"judgement_mode": "unknown"}, "invalid_fields"),
    ("skill", {"unknown_option": "private-value"}, "invalid_fields"),
    ("skill", {"version": "old"}, "invalid_fields"),
    ("agent", {"skills": []}, "invalid_fields"),
    ("agent", {"skills": ["invalid-check"]}, "invalid_fields"),
    ("agent", {"skills": ["data-leakage-detection"] * 2}, "invalid_fields"),
    ("agent", {"policy_id": "unknown"}, "policy_invalid"),
    ("agent", {"evaluation_model": "unknown"}, "model_invalid"),
    ("agent", {"approval_id": "unknown"}, "approval_invalid"),
])
def test_invalid_fields_do_not_write(api, kind, changes, code):
    client, _, skill_path, agent_path = api
    response = client.post(ROOT + "/" + kind, json=body(client, kind, **changes))
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "openapi_profiles." + code
    assert "private-value" not in response.text
    assert not skill_path.exists() and not agent_path.exists()


@pytest.mark.parametrize("mutation", ["disabled_policy", "passive_policy", "no_conversation", "no_multi_turn", "disabled_model", "disabled_provider"])
def test_policy_and_model_dependencies(api, mutation):
    client, sessions, *_ = api
    with sessions() as db:
        policy = db.query(models.SecurityScanPolicy).one()
        if mutation == "disabled_policy": policy.enabled = False
        elif mutation == "passive_policy": policy.execution_mode = "passive"
        elif mutation == "no_conversation": policy.allowed_capabilities_json = '[]'
        elif mutation == "no_multi_turn": policy.allowed_capabilities_json = '["conversation"]'
        elif mutation == "disabled_model": db.query(models.ModelEndpoint).one().enabled = False
        else: db.query(models.ModelProvider).one().enabled = False
        db.commit()
    response = client.post(ROOT + "/agent", json=body(client, "agent", conversation_mode="multi_turn"))
    assert response.status_code == 422
    if mutation in {"disabled_model", "disabled_provider"}:
        assert client.get(ROOT + "/options").json()["models"] == []


def test_stale_duplicate_and_missing_profile(api):
    client, _, path, _ = api
    request = body(client)
    assert client.post(ROOT + "/skill", json=request).status_code == 201
    before = path.read_bytes()
    stale = client.put(ROOT + "/skill", json=request)
    assert stale.status_code == 409 and stale.json()["error_code"] == "openapi_profiles.conflict"
    assert client.post(ROOT + "/skill", json=body(client)).json()["error_code"] == "openapi_profiles.exists"
    assert client.put(ROOT + "/skill", json=body(client, profile_id="missing")).status_code == 404
    assert path.read_bytes() == before


def test_concurrent_writers_and_preserved_other_profile(api):
    client, _, path, _ = api
    first = body(client)
    other = {**first, "profile_id": "other"}
    def write(request):
        return client.post(ROOT + "/skill", json=request).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, [first, other]))
    assert sorted(results) == [201, 409]
    winner = next(iter(json.loads(path.read_text())["profiles"]))
    previous = json.loads(path.read_text())["profiles"][winner]
    assert client.post(ROOT + "/skill", json=body(client, profile_id="third")).status_code == 201
    assert json.loads(path.read_text())["profiles"][winner] == previous


def test_invalid_file_and_failed_replace_preserve_original(api, monkeypatch):
    client, _, path, _ = api
    request = body(client)
    path.write_text('{"private": "broken')
    original = path.read_bytes()
    response = client.get(ROOT + "/skill")
    assert response.status_code == 422 and "private" not in response.text
    assert client.post(ROOT + "/skill", json=request).status_code == 422
    assert path.read_bytes() == original
    path.write_text('{"profiles": {}, "callbacks": {}}')
    request = body(client)
    original = path.read_bytes()
    def fail(*args): raise OSError("private filesystem path")
    monkeypatch.setattr(service.os, "replace", fail)
    response = client.post(ROOT + "/skill", json=request)
    assert response.status_code == 503 and "private" not in response.text
    assert path.read_bytes() == original and list(path.parent.glob(".openapi-profile-*")) == []


def test_management_permissions_and_audit(api):
    client, sessions, *_ = api
    request = body(client)
    with sessions() as db:
        iam.initialize(db)
        db.add(models.Role(name="profile_reader", display_name="Profile reader"))
        db.add(models.RolePermission(role_name="profile_reader", permission_code="external_access:view"))
        db.add_all([models.User(username="reader", role="profile_reader", hashed_password="unused"),
                    models.User(username="admin", role="super_admin", hashed_password="unused")])
        db.commit()
    client.app.dependency_overrides.pop(auth.get_current_admin_user)
    assert client.get(ROOT + "/skill").status_code == 401
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "reader"})
    assert client.get(ROOT + "/options").status_code == 200
    assert client.get(ROOT + "/skill").status_code == 200
    assert client.post(ROOT + "/skill", json=request).status_code == 403
    assert client.put(ROOT + "/skill", json=request).status_code == 403
    client.headers["Authorization"] = "Bearer " + auth.create_access_token({"sub": "admin"})
    assert client.post(ROOT + "/skill", json=request).status_code == 201
    assert client.put(ROOT + "/skill", json=body(client, use_llm=True)).status_code == 200
    with sessions() as db:
        assert db.query(models.ManagementAudit).filter_by(module="external_access", action="create", outcome="success").count() >= 1
        assert db.query(models.ManagementAudit).filter_by(module="external_access", action="update", outcome="success").count() == 1


def test_errors_localized_and_request_validation_safe(api):
    client = api[0]
    request = body(client, platform_ids=["unknown"])
    zh = client.post(ROOT + "/skill", json=request).json()
    en = client.post(ROOT + "/skill", json=request, headers={"Accept-Language": "en-US"}).json()
    assert zh["error_code"] == en["error_code"] and zh["detail"] != en["detail"]
    response = client.post(ROOT + "/skill", json={**request, "settings": "private-invalid-value"})
    assert response.status_code == 422 and "private-invalid-value" not in response.text


def test_agent_update_preserves_job_report_callback_gateway_snapshots(agent_api, tmp_path):
    client, sessions, issued, *_ = agent_api
    client.app.include_router(openapi_profiles.router, prefix="/api/v1")
    client.app.dependency_overrides[native.get_manager] = lambda: SimpleNamespace(registry=SimpleNamespace(data_dir=tmp_path))
    register(agent_api)
    connection = ready(agent_api)
    first = evaluate(agent_api, connection).json()["data"]["task_id"]
    request = body(client, "agent", malicious_rule_ids=["new-rule"])
    response = client.put(ROOT + "/agent", json=request)
    assert response.status_code == 200, response.text
    version = response.json()["items"][0]["version"]
    second = evaluate(agent_api, connection, business_request_id="business-2").json()["data"]["task_id"]
    with sessions() as db:
        assert json.loads(db.get(ExternalAgentJob, first).profile_json)["version"] == "1"
        assert json.loads(db.get(ExternalAgentJob, second).profile_json)["version"] == version
    claimed = claim(agent_api)
    assert claimed["task"]["task_id"] == first
    complete(agent_api, claimed, cases=[{"external_case_id": "one", "category": "data-leakage-detection", "title": "Check", "status": "passed"}])
    result = client.get("/openapi/v1/agent-evaluations/" + first + "/result", headers=bearer(issued))
    assert result.status_code == 200, result.text
    assert result.json()["data"]["profile_version"] == "1"
    with sessions() as db:
        job = db.get(ExternalAgentJob, first)
        original = job.report_json
        callback = db.query(ExternalResultEvent).filter_by(task_id=first).one().payload_json
        gateway = db.query(ExternalGatewayEvent).filter_by(task_id=first).one().payload_json
    assert client.put(ROOT + "/agent", json=body(client, "agent", malicious_rule_ids=["another-rule"])).status_code == 200
    with sessions() as db:
        assert db.get(ExternalAgentJob, first).report_json == original
        assert db.query(ExternalResultEvent).filter_by(task_id=first).one().payload_json == callback
        assert db.query(ExternalGatewayEvent).filter_by(task_id=first).one().payload_json == gateway


def test_skill_update_freezes_accepted_task_and_changes_new_submissions(skill_api):
    client, sessions, _, queue, issued, _ = skill_api
    client.app.include_router(openapi_profiles.router, prefix="/api/v1")
    first_url = url(submit(skill_api))
    response = client.put(ROOT + "/skill", json=body(client, use_sandbox=False, judgement_mode="strict"))
    assert response.status_code == 200, response.text
    version = response.json()["items"][0]["version"]
    second_url = url(submit(skill_api, business_request_id="business-2", content=archive({"SKILL.md": "---\nname: another-skill\ndescription: sample\n---\n"})))
    with sessions() as db:
        first = db.get(ExternalSkillScan, first_url.rsplit("/", 1)[1])
        second = db.get(ExternalSkillScan, second_url.rsplit("/", 1)[1])
        assert json.loads(first.profile_json)["version"] == "1"
        assert json.loads(first.profile_json)["judgement_mode"] == "balanced"
        assert json.loads(second.profile_json)["version"] == version
        assert json.loads(second.profile_json)["judgement_mode"] == "strict"
    queue.finish()
    assert client.get(first_url + "/result", headers=bearer(issued)).json()["data"]["profile_version"] == "1"
