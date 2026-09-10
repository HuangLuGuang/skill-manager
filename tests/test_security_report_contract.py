from backend.security_report_contract import (
    DECISION_CRITERIA_VERSION,
    REPORT_CONTRACT_SCHEMA_VERSION,
    REPORT_TEMPLATE_VERSION,
    build_report_contract,
    legacy_unversioned_report_contract,
)


def test_report_contract_is_versioned_and_scan_kind_specific():
    expected_scope_rules = {
        "control_plane_validation": "control_plane_validation_only",
        "agent_risk_scan": "agent_dynamic_observation_is_bounded",
        "mcp_risk_scan": "mcp_metadata_snapshot_only",
    }
    for scan_kind, scope_rule in expected_scope_rules.items():
        snapshot = build_report_contract(scan_kind)
        assert snapshot["schema_version"] == REPORT_CONTRACT_SCHEMA_VERSION
        assert snapshot["snapshot_status"] == "frozen"
        assert snapshot["report_template_version"] == REPORT_TEMPLATE_VERSION
        assert snapshot["decision_criteria_version"] == DECISION_CRITERIA_VERSION
        assert snapshot["scan_kind"] == scan_kind
        assert snapshot["decision_criteria"][-1]["rule_id"] == scope_rule
        assert snapshot["case_status_values"] == [
            "passed",
            "failed",
            "blocked",
            "error",
            "unverified",
        ]


def test_report_contract_does_not_equate_success_or_empty_findings_with_safety():
    rules = {item["rule_id"]: item for item in build_report_contract("agent_risk_scan")["decision_criteria"]}
    assert rules["task_succeeded_is_execution_result_only"]["outcome"] == "result_contract_satisfied_not_safe"
    assert rules["empty_findings_is_not_safe"]["outcome"] == "no_finding_observed_not_safe"
    assert rules["case_blocked_or_error_is_unverified"]["outcome"] == "unverified"
    assert "unverified" in rules["case_blocked_or_error_is_unverified"]["when"]["status_in"]
    assert rules["missing_evidence_is_unverified"]["outcome"] == "unverified_evidence"


def test_report_contract_builds_independent_snapshots_and_marks_legacy_records():
    first = build_report_contract("mcp_risk_scan")
    first["template"]["section_order"].append("mutated")
    second = build_report_contract("mcp_risk_scan")
    assert "mutated" not in second["template"]["section_order"]
    assert legacy_unversioned_report_contract() == {
        "schema_version": None,
        "snapshot_status": "legacy_unversioned",
        "report_template_version": None,
        "decision_criteria_version": None,
    }
