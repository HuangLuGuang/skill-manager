import copy

from backend.aidr_plugin_status import PluginStatusRow
from tests.test_aidr_api import service


def report():
    return {"schema_version": 1, "stream_id": "a"*32, "receiver_instance": "b"*32, "report_sequence": "1", "status": {
        "agent": "codex", "host_version": "codex-cli 0.158.0-alpha.2.1", "version_status": "adapter_target",
        "installed": True, "enabled": True, "plugin_version": "0.1.0", "plugin_id": "aidr-codex@local",
        "source_code": "aidr_plugin_enabled_trust_unknown", "hook_trust": "unknown", "reported_at": "2026-09-27T00:00:00Z",
        "receiver_code": "aidr_hook_receiver_not_checked", "configuration_digest": "c"*64,
        "source_kind": "declared_local_source", "files_code": "aidr_plugin_files_observed", "files_digest": "d"*64,
        "scope_digest": "e"*64}}


def send(client, body, target="one"):
    return client.post(f"/api/v1/clients/{target}/aidr/hook-plugin-status", json=body, headers={"authorization": "Bearer test-one"})


def read(client):
    return client.get("/api/v1/clients/one/aidr/hook-policy").json()["plugins"]["items"][0]


def test_persistent_baseline_replay_restart_and_unreadable(service, monkeypatch):
    client, factory = service
    monkeypatch.setattr("backend.aidr_plugin_status.time.time", lambda: 1000)
    body = report()
    assert send(client, body).status_code == 200
    assert read(client)["change"]["code"] == "aidr_plugin_baseline_established"
    offline = copy.deepcopy(body)
    offline["report_sequence"] = "2"
    offline["status"].update(installed=None, enabled=None, source_code="aidr_plugin_source_unreadable", configuration_digest="", files_digest="", files_code="aidr_plugin_files_unknown", source_kind="unknown")
    assert send(client, offline).status_code == 200
    assert read(client)["report"]["status"]["installed"] is None
    body["report_sequence"] = "3"
    body["receiver_instance"] = "f"*32
    body["status"].update(enabled=False, source_code="aidr_plugin_disabled", configuration_digest="f"*64)
    assert send(client, body).status_code == 200
    item = read(client)
    assert item["change"]["fields"] == ["native_configuration"]
    assert item["change"]["before"]["enabled"] is True and item["change"]["after"]["enabled"] is False
    monkeypatch.setattr("backend.aidr_plugin_status.time.time", lambda: 1181)
    assert send(client, offline).status_code == 200
    assert send(client, body).status_code == 200
    assert read(client)["stale"] and read(client)["received_at"] == "1000"
    body["report_sequence"] = "4"
    assert send(client, body).status_code == 200
    assert read(client)["change"] == item["change"]
    assert not read(client)["stale"]
    with factory() as db:
        assert db.query(PluginStatusRow).count() == 1


def test_file_read_gap_does_not_reset_baseline_or_grant_access(service):
    client, _ = service
    body = report()
    assert send(client, body).status_code == 200
    assert send(client, body, "two").status_code == 403
    assert client.get("/api/v1/clients/two/aidr/hook-policy").status_code == 404
    body["report_sequence"] = "2"
    body["status"].update(files_digest="", files_code="aidr_plugin_files_unreadable")
    assert send(client, body).status_code == 200
    assert read(client)["report"]["status"]["installed"] is True
    body["report_sequence"] = "3"
    body["status"].update(files_digest="f"*64, files_code="aidr_plugin_files_observed")
    assert send(client, body).status_code == 200
    assert read(client)["change"]["fields"] == ["declared_files"]
    body["status"]["hook_trust"] = "trusted"
    assert send(client, body).status_code == 422
    body["status"]["hook_trust"] = "unknown"
    body["status"]["raw_config"] = "not-allowed"
    assert send(client, body).status_code == 422


def test_status_capacity_and_scope_isolation(service):
    client, _ = service
    for index in range(64):
        body = report()
        body["status"]["scope_digest"] = f"{index:064x}"
        assert send(client, body).status_code == 200
    page = client.get("/api/v1/clients/one/aidr/hook-policy").json()["plugins"]
    assert page["truncated"] and len(page["items"]) == 20
    assert send(client, report()).status_code == 429
    body = report()
    body["status"]["scope_digest"] = "0"*64
    body["report_sequence"] = "2"
    assert send(client, body).status_code == 200


def test_interface_compatibility_report_keeps_native_trust_separate(service):
    client, _ = service
    body = report()
    body['status'].update(host_version='codex-cli 0.999.42', version_status='interface_compatible')
    assert send(client, body).status_code == 200
    observed = read(client)['report']['status']
    assert observed['version_status'] == 'interface_compatible'
    assert observed['hook_trust'] == 'unknown'
    body['report_sequence'] = '2'
    body['status']['version_status'] = 'invented'
    assert send(client, body).status_code == 422


def test_local_observation_preserves_evidence_and_does_not_invent_host_version_drift(service):
    client, _ = service
    body = report()
    assert send(client, body).status_code == 200
    body['report_sequence'] = '2'
    body['status'].update(host_version='', version_status='adapter_available')
    assert send(client, body).status_code == 200
    item = read(client)
    assert item['change']['fields'] == []
    assert item['report']['status']['hook_trust'] == 'unknown'
    assert item['report']['status']['version_status'] == 'adapter_available'
    body['report_sequence'] = '3'
    body['status'].update(files_digest='f'*64)
    assert send(client, body).status_code == 200
    assert read(client)['change']['fields'] == ['declared_files']
    page = client.get('/api/v1/clients/one/aidr/hook-policy').json()['plugins']
    assert page['evidence_type'] == 'plugin_configuration_report'
