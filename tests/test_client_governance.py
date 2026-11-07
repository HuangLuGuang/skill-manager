import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import client_governance as governance, models
from backend.api_errors import ApiError
from backend.sqlite_db import Base


@pytest.fixture
def db(tmp_path):
    from backend.runtime_governance import HookEnrollment  # Register the table used by policy_view before create_all.
    engine = create_engine(f"sqlite:///{tmp_path / 'governance.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_client(db, client_id="client-1", protocol=1, is_new=True):
    row = models.ManagedClient(client_id=client_id, name=client_id, hostname="host", os="linux", arch="amd64", client_version="dev", registered_by="admin")
    db.add(row)
    governance.record_protocol(db, client_id, protocol, is_new=is_new)
    db.commit()
    return row


def apply(db, scope, rules):
    view = governance.policy_view(db, None if scope == governance.DEFAULT_SCOPE else scope)
    change = governance.PolicyChange(rules=rules, expected_version=view["version"])
    change.preview_id = governance.preview(db, scope, change)["preview_id"]
    result = governance.save_policy(db, scope, change, SimpleNamespace(username="admin"))
    db.commit()
    return result


@pytest.mark.parametrize("enrollment_enabled", [True, False])
def test_runtime_preview_matches_saved_enrollment_scope(db, enrollment_enabled):
    from backend.runtime_governance import HookEnrollment
    add_client(db, protocol=2)
    db.add(HookEnrollment(client_id="client-1", hosts_json=json.dumps(["codebuddy", "trae-cn"])))
    db.commit()
    current = governance.policy_view(db, "client-1")
    base = governance.RuntimeGovernanceConfig().model_dump()
    base.update(enabled=True, hosts=["codex"], log_sources=["codex"],
                allow_user_enrollment=enrollment_enabled)
    base["channels"] = {"logs": True, "hooks": True, "system": False}
    change = governance.PolicyChange(rules={}, expected_version=current["version"], runtime_governance=base)
    result = governance.preview(db, "client-1", change)
    change.preview_id = result["preview_id"]
    saved = governance.save_policy(db, "client-1", change, SimpleNamespace(username="admin"))
    assert result["runtime_proposed"] == saved["runtime_governance"]
    assert ("codebuddy" in result["runtime_proposed"]["hosts"]) == enrollment_enabled
    assert ("codebuddy" in result["runtime_proposed"]["log_sources"]) == enrollment_enabled
    assert db.get(HookEnrollment, "client-1").hosts_json == json.dumps(["codebuddy", "trae-cn"])


def test_new_clients_default_to_record_and_inherit_per_rule(db):
    add_client(db, protocol=2)
    assert governance.policy_view(db, "client-1")["rules"] == governance.DEFAULT_RULES
    apply(db, governance.DEFAULT_SCOPE, {"malicious": "quarantine"})
    own = apply(db, "client-1", {"unverified": "submit_scan"})
    assert own["rules"]["malicious"] == "quarantine"
    assert own["rules"]["unverified"] == "submit_scan"
    assert own["sources"]["malicious"] == "default"
    assert own["sources"]["unverified"] == "client"
    assert own["enabled"]


@pytest.mark.parametrize("mode", ["audit", "block", "repair"])
def test_existing_clients_auto_enable_once_preserving_original_policy(db, mode):
    client = add_client(db, protocol=0, is_new=False)
    client.policy_mode = mode
    db.commit()
    apply(db, governance.DEFAULT_SCOPE, {"unverified": "quarantine"})
    assert not governance.policy_view(db, "client-1")["enabled"]
    governance.record_protocol(db, "client-1", 1)
    db.commit()
    enabled = governance.policy_view(db, "client-1")
    assert enabled["enabled"]
    assert enabled["rules"] == governance.legacy_policy_rules(mode)
    changed = apply(db, "client-1", {"malicious": "uninstall"})
    governance.record_protocol(db, "client-1", 1)
    db.commit()
    assert governance.policy_view(db, "client-1") == changed


def test_previously_supported_but_disabled_client_activates_on_next_heartbeat(db):
    add_client(db)
    row = db.get(models.ClientGovernancePolicy, "client-1")
    row.enabled = False
    db.commit()
    governance.record_protocol(db, "client-1", 1)
    db.commit()
    assert governance.policy_view(db, "client-1")["enabled"]
    assert governance.policy_view(db, "client-1")["rules"] == governance.DEFAULT_RULES


def test_preview_invalidates_when_inventory_or_policy_changes(db):
    add_client(db)
    change = governance.PolicyChange(rules={"malicious": "quarantine"}, expected_version="0:0")
    change.preview_id = governance.preview(db, "client-1", change)["preview_id"]
    db.add(models.ClientSkillInstall(client_id="client-1", agent_type="codex", skill_name="new-skill", skill_path="/skills/new", signature="changed"))
    db.commit()
    with pytest.raises(ApiError) as error:
        governance.save_policy(db, "client-1", change, SimpleNamespace(username="admin"))
    assert error.value.code == "client.policy_preview_required"
    db.rollback()
    apply(db, governance.DEFAULT_SCOPE, {"malicious": "quarantine"})
    with pytest.raises(ApiError) as error:
        governance.preview(db, "client-1", change)
    assert error.value.code == "client.policy_changed"


def test_default_preview_excludes_only_clients_not_yet_upgraded(db):
    add_client(db, "active")
    add_client(db, "legacy", protocol=0, is_new=False)
    add_client(db, "old-binary", protocol=0, is_new=False)
    change = governance.PolicyChange(rules={"unverified": "quarantine"}, expected_version="0:0")
    result = governance.preview(db, governance.DEFAULT_SCOPE, change)
    assert result["client_count"] == 1
    assert result["clients"] == [{"client_id": "active", "client_name": "active", "version": "0:0"}]
    assert result["items"] == []
    assert result["excluded_clients"] == [
        {"client_id": "legacy", "client_name": "legacy", "reason": "upgrade_required"},
        {"client_id": "old-binary", "client_name": "old-binary", "reason": "upgrade_required"},
    ]
    assert not governance.policy_view(db, "legacy")["enabled"]
    governance.record_protocol(db, "legacy", 1)
    db.commit()
    refreshed = governance.preview(db, governance.DEFAULT_SCOPE, change)
    assert refreshed["client_count"] == 2
    assert refreshed["preview_id"] != result["preview_id"]


@pytest.mark.parametrize("rules", [{"unverified": "uninstall"}, {"malicious": "submit_scan"}, {"other": "record"}, {"unverified": "unknown"}])
def test_rule_actions_are_validated(rules):
    with pytest.raises(ApiError):
        governance.PolicyChange(rules=rules, expected_version="0:0")


def test_preview_predicts_effective_actions_and_requires_current_observations(db):
    add_client(db)
    apply(db, "client-1", {"malicious": "record"})
    version = governance.policy_view(db, "client-1")["version"]
    for name, trigger, signature, observed_version in [
        ("changed", "unverified", "same", version),
        ("override", "malicious", "same", version),
        ("edited", "unverified", "old", version),
        ("stale", "unverified", "same", "0:0"),
        ("trusted", "", "same", version),
        ("expired", "unverified", "same", version),
        ("pending", "unverified", "same", version),
    ]:
        db.add(models.ClientSkillInstall(client_id="client-1", agent_type="codex", skill_name=name,
            skill_path=f"/skills/{name}", signature="same", governance_json=json.dumps({
                "signature": signature, "policy_version": observed_version, "trigger": trigger,
                "last_seen_at": (datetime.now(timezone.utc) - timedelta(hours=1 if name == "expired" else 0)).isoformat(),
                "certification": "confirmation_pending" if name == "pending" else "certified" if not trigger else "unverified",
            })))
    db.commit()
    change = governance.PolicyChange(rules={"unverified": "quarantine", "malicious": "uninstall"}, expected_version="0:0")
    rows = {row["skill_name"]: row for row in governance.preview(db, governance.DEFAULT_SCOPE, change)["items"]}
    assert (rows["changed"]["current_action"], rows["changed"]["proposed_action"], rows["changed"]["effect"]) == ("record", "quarantine", "changed")
    assert rows["override"]["client_override"] and rows["override"]["effect"] == "unchanged"
    assert rows["override"]["proposed_action"] == "record"
    assert rows["edited"]["effect"] == rows["stale"]["effect"] == "recheck"
    assert rows["edited"]["proposed_action"] is None
    assert rows["edited"]["recheck_reason"] == "content_changed"
    assert rows["stale"]["recheck_reason"] == "policy_changed"
    assert rows["trusted"]["proposed_action"] == "none"
    assert rows["expired"]["effect"] == rows["pending"]["effect"] == "recheck"
    assert rows["expired"]["recheck_reason"] == "observation_expired"
    assert rows["pending"]["recheck_reason"] == "classification_pending"
    # Changing to recording only must still show existing directories and effects.
    record = governance.PolicyChange(rules={}, expected_version=version)
    assert len(governance.preview(db, "client-1", record)["items"]) == 7


@pytest.mark.parametrize("status", ["broken_link", "unscannable", "external_link"])
def test_preview_explains_unreadable_skill_instead_of_requesting_fresh_data(db, status):
    add_client(db)
    db.add(models.ClientSkillInstall(client_id="client-1", agent_type="codex", skill_name="unreadable", skill_path="/skills/unreadable", status=status))
    db.commit()
    result = governance.preview(db, "client-1", governance.PolicyChange(rules={}, expected_version="0:0"))
    assert result["items"][0]["effect"] == "recheck"
    assert result["items"][0]["recheck_reason"] == status


def test_record_only_and_rejected_scan_rules_are_independent(db):
    add_client(db, protocol=2)
    rules = {"unverified": "record_only", "trusted_content_changed": "submit_scan",
             "trusted_scan_rejected": "restore_trusted", "unverified_scan_rejected": "quarantine",
             "malicious": "record"}
    result = apply(db, governance.DEFAULT_SCOPE, rules)
    assert all(result["rules"][key] == value for key, value in rules.items())
    own = apply(db, "client-1", {"trusted_scan_rejected": "record_only"})
    assert own["rules"]["trusted_scan_rejected"] == "record_only"
    assert own["defaults"]["trusted_scan_rejected"] == "restore_trusted"
    assert own["rules"]["trusted_content_changed"] == "submit_scan"
    with pytest.raises(ApiError):
        governance.PolicyChange(rules={"unverified_scan_rejected": "restore_trusted"}, expected_version=result["version"])


@pytest.mark.parametrize("matches,status,report,expected", [
    (True, "REJECTED", {}, True),
    (True, "REJECTED", {"vetting_failed": True}, False),
    (True, "PENDING", {}, False),
    (True, "VETTED", {}, False),
    (False, "REJECTED", {}, False),
])
def test_content_rejection_excludes_processing_failures(matches, status, report, expected):
    entry = SimpleNamespace(status=status, vetting=SimpleNamespace(scan_report=report))
    assert governance.content_rejected(entry, matches) is expected


def test_advanced_actions_require_updated_clients_and_survive_upgrade(db):
    add_client(db, protocol=1)
    change = governance.PolicyChange(rules={"unverified": "record_only"}, expected_version="0:0")
    result = governance.preview(db, governance.DEFAULT_SCOPE, change)
    assert result["incompatible_clients"][0]["rules"] == ["unverified"]
    change.preview_id = result["preview_id"]
    with pytest.raises(ApiError) as error:
        governance.save_policy(db, governance.DEFAULT_SCOPE, change, SimpleNamespace(username="admin"))
    assert error.value.code == "client.policy_capability_required"
    db.rollback()
    governance.record_protocol(db, "client-1", 2)
    db.commit()
    assert governance.policy_view(db, "client-1")["advanced_supported"]
    assert not governance.preview(db, governance.DEFAULT_SCOPE, change)["incompatible_clients"]
    apply(db, governance.DEFAULT_SCOPE, {"unverified": "record_only", "trusted_scan_rejected": "restore_trusted"})
    governance.record_protocol(db, "client-1", 1)
    db.commit()
    assert governance.policy_view(db, "client-1")["incompatible_rules"] == ["trusted_scan_rejected", "unverified"]
    governance.record_protocol(db, "client-1", 2)
    db.commit()
    assert not governance.policy_view(db, "client-1")["incompatible_rules"]
    assert governance.policy_view(db, "client-1")["rules"]["unverified"] == "record_only"


def test_scan_followup_alert_also_requires_capability(db):
    add_client(db, protocol=1)
    change = governance.PolicyChange(rules={"unverified": "submit_scan"}, expected_version="0:0")
    result = governance.preview(db, governance.DEFAULT_SCOPE, change)
    assert result["incompatible_clients"][0]["rules"] == ["unverified_scan_rejected"]

def test_noop_save_and_unrelated_legacy_rules(db):
    add_client(db, protocol=2)
    scope = governance.DEFAULT_SCOPE
    apply(db, scope, {"unverified": "record_only", "malicious": "uninstall"})
    governance.record_protocol(db, "client-1", 1)
    db.commit()
    current = governance.policy_view(db)
    change = governance.PolicyChange(expected_version=current["version"], rules=current["rules"],
                                     desktop_menu_visibility=current["desktop_menu_visibility"])
    result = governance.preview(db, scope, change)
    assert not result["has_changes"] and not result["contains_uninstall"]
    change.preview_id = result["preview_id"]
    tasks = db.query(models.ClientTask).count()
    assert governance.save_policy(db, scope, change, SimpleNamespace(username="admin"))["version"] == current["version"]
    assert db.query(models.ClientTask).count() == tasks
    db.commit()
    change = governance.PolicyChange(expected_version=current["version"], rules=current["rules"],
                                     runtime_governance={**current["runtime_governance"], "hosts": ["codex"]})
    result = governance.preview(db, scope, change)
    assert result["has_changes"] and not result["incompatible_clients"] and not result["contains_uninstall"]
    change.preview_id = result["preview_id"]
    assert governance.save_policy(db, scope, change, SimpleNamespace(username="admin"))["runtime_governance"]["hosts"] == ["codex"]


def test_inheriting_uninstall_warns_and_equal_override_can_be_saved(db):
    add_client(db, protocol=2)
    apply(db, governance.DEFAULT_SCOPE, {"malicious": "uninstall"})
    apply(db, "client-1", {"malicious": "record"})
    current = governance.policy_view(db, "client-1")
    inherit = governance.PolicyChange(expected_version=current["version"], rules={})
    assert governance.preview(db, "client-1", inherit)["contains_uninstall"]
    override = governance.PolicyChange(expected_version=current["version"], rules={"malicious": "record", "unverified": current["rules"]["unverified"]})
    result = governance.preview(db, "client-1", override)
    assert result["has_changes"] and not result["contains_uninstall"]
