from backend.aidr_hook_drift import compare
from tests.test_aidr_enforcement import control
from tests.test_aidr_api import service


def policy(default="deny", rules=(), revision="1"):
    return {"revision": revision, "default_action": default, "rules": list(rules)}


def rule(ident, decision, agent="*", tool="*"):
    return dict(id=ident, agent=agent, tool=tool, decision=decision)


def test_wildcard_expansion_identifies_removed_restriction():
    old = policy("deny", [rule("allow-all", "allow"), rule("shell", "deny", "codex", "Bash")])
    new = policy("deny", [rule("allow-all", "allow")], "2")
    result = compare(old, new)
    assert result["counts"] == {"expanded": 1, "restricted": 0, "unchanged": 3, "baseline_unknown": 0}
    row = result["items"][0]
    assert (row["agent"], row["tool"], row["before"]["rule_id"], row["after"]["rule_id"]) == ("codex", "Bash", "shell", "allow-all")
    assert result["rule_changes"]["removed"] == ["shell"]


def test_shadowed_allow_does_not_falsely_expand_and_order_is_irrelevant():
    old = policy("deny", [rule("block", "deny")])
    new = policy("allow", [rule("permit", "allow"), rule("block", "deny")], "2")
    result = compare(old, new)
    assert result["counts"]["expanded"] == 0 and result["conflict_partitions"] == 2
    assert all(x["after"]["rule_id"] == "block" for x in result["items"])
    assert result == compare(old, {**new, "rules": list(reversed(new["rules"]))})


def test_default_changes_other_tools_and_first_policy_is_not_applied_claim():
    result = compare(policy("deny"), policy("ask", [rule("shell", "deny", tool="Bash")], "2"))
    assert result["counts"]["expanded"] == 2
    assert all(x["scope"] == "other_tools" and x["tool"] is None for x in result["items"])
    initial = compare(None, policy("allow"))
    assert initial["counts"]["expanded"] == 0 and initial["counts"]["baseline_unknown"] == 2


def test_detail_budget_does_not_truncate_aggregate_analysis():
    old = policy("deny", [rule(f"r{i}", "deny", tool=f"tool-{i}") for i in range(128)])
    new = policy("allow", [rule(f"n{i}", "allow", tool=f"next-{i}") for i in range(128)], "2")
    result = compare(old, new)
    assert result["counts"]["expanded"] == 514 and result["partition_count"] == 514
    assert len(result["items"]) == 64 and result["details_truncated"]


def test_policy_api_retains_history_and_device_access(control):
    client, factory, _ = control
    api = "/api/v1/clients/one/aidr/hook-policy"
    assert client.get(api).json()["analysis"] is None
    body = dict(expected_revision="0", lifetime_seconds=3600, default_action="deny", rules=[])
    assert client.put(api, json=body).status_code == 200
    body.update(expected_revision="1", default_action="allow")
    result = client.put(api, json=body)
    assert result.status_code == 200
    analysis = result.json()["analysis"]
    assert analysis["counts"]["expanded"] == 2 and analysis["client_application"] == "unknown"
    assert analysis["previous_revision"] == "1" and analysis["current_revision"] == "2"
    assert client.get(api).json()["analysis"]["counts"] == analysis["counts"]
    assert client.get("/api/v1/clients/two/aidr/hook-policy").status_code == 404
