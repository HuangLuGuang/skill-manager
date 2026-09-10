from __future__ import annotations

from copy import deepcopy
from typing import Any

REPORT_CONTRACT_SCHEMA_VERSION = "security-report-contract@4"
REPORT_TEMPLATE_VERSION = "agent-security-report-template@4"
DECISION_CRITERIA_VERSION = "agent-security-decision-criteria@2"

_SUPPORTED_SCAN_KINDS = {
    "control_plane_validation",
    "agent_risk_scan",
    "mcp_risk_scan",
    "llm_redteam_scan",
    "ai_infrastructure_vulnerability_scan",
    "dify_asset_inventory",
}

_TEMPLATE = {
    "section_order": [
        "task_summary",
        "scope_and_coverage",
        "decision_criteria",
        "cases",
        "findings",
        "artifacts",
        "limitations",
    ],
    "finding_fields": [
        "finding_id",
        "case_id",
        "trace_id",
        "event_id",
        "finding_code",
        "risk_codes",
        "severity",
        "status",
        "title",
        "description",
        "evidence",
        "source",
        "confidence",
        "fingerprint",
        "decision_criteria_version",
    ],
    "comparison_buckets": [
        "new",
        "unchanged",
        "resolved_or_not_reproduced",
        "unable_to_retest",
    ],
}

_COMMON_CRITERIA = [
    {
        "rule_id": "task_succeeded_is_execution_result_only",
        "subject": "task",
        "when": {"status": "succeeded"},
        "outcome": "result_contract_satisfied_not_safe",
    },
    {
        "rule_id": "case_passed_means_not_observed",
        "subject": "case",
        "when": {"status": "passed"},
        "outcome": "no_finding_observed_in_executed_case",
    },
    {
        "rule_id": "case_failed_means_finding_observed",
        "subject": "case",
        "when": {"status": "failed"},
        "outcome": "finding_observed",
    },
    {
        "rule_id": "case_blocked_or_error_is_unverified",
        "subject": "case",
        "when": {"status_in": ["blocked", "error", "unverified"]},
        "outcome": "unverified",
    },
    {
        "rule_id": "empty_findings_is_not_safe",
        "subject": "report",
        "when": {"finding_count": 0},
        "outcome": "no_finding_observed_not_safe",
    },
    {
        "rule_id": "missing_evidence_is_unverified",
        "subject": "finding",
        "when": {"evidence": "empty"},
        "outcome": "unverified_evidence",
    },
    {
        "rule_id": "comparison_resolution_requires_equivalent_successful_scan",
        "subject": "comparison",
        "requires": ["baseline_succeeded", "current_succeeded", "coverage_match", "engine_match"],
        "outcome": "resolved_or_not_reproduced",
    },
]

_SCAN_KIND_CRITERIA = {
    "control_plane_validation": {
        "rule_id": "control_plane_validation_only",
        "subject": "scope",
        "outcome": "control_plane_verified_dynamic_risk_unverified",
    },
    "agent_risk_scan": {
        "rule_id": "agent_dynamic_observation_is_bounded",
        "subject": "scope",
        "outcome": "only_executed_cases_and_rounds_observed",
    },
    "mcp_risk_scan": {
        "rule_id": "mcp_metadata_snapshot_only",
        "subject": "scope",
        "outcome": "tool_behavior_unverified_no_side_effect_calls",
    },
    "llm_redteam_scan": {
        "rule_id": "llm_attack_case_requires_execution_and_evaluation",
        "subject": "scope",
        "requires": ["target_call_completed", "evaluator_completed"],
        "outcome": "attack_resisted_or_jailbreak_signal_for_executed_prompt_only",
    },
    "ai_infrastructure_vulnerability_scan": {
        "rule_id": "infrastructure_cve_requires_version_match_evidence",
        "subject": "scope",
        "requires": ["component_fingerprint", "component_version", "version_rule_match"],
        "outcome": "confirmed_version_rule_match_not_port_only",
    },
    "dify_asset_inventory": {
        "rule_id": "dify_inventory_separates_configuration_discovery_and_execution",
        "subject": "scope",
        "outcome": "asset_inventory_is_evidence_scoped_not_complete_verification",
    },
}


def build_report_contract(scan_kind: str) -> dict[str, Any]:
    """Build the immutable report contract snapshot stored when a task is created."""

    if scan_kind not in _SUPPORTED_SCAN_KINDS:
        raise ValueError(f"unsupported scan kind: {scan_kind}")
    return deepcopy(
        {
            "schema_version": REPORT_CONTRACT_SCHEMA_VERSION,
            "snapshot_status": "frozen",
            "report_template_version": REPORT_TEMPLATE_VERSION,
            "decision_criteria_version": DECISION_CRITERIA_VERSION,
            "scan_kind": scan_kind,
            "template": _TEMPLATE,
            "decision_criteria": [*_COMMON_CRITERIA, _SCAN_KIND_CRITERIA[scan_kind]],
            "severity_values": ["critical", "high", "medium", "low", "info"],
            "case_status_values": ["passed", "failed", "blocked", "error", "unverified"],
            "finding_status_values": ["open", "accepted", "resolved", "false_positive"],
        }
    )


def legacy_unversioned_report_contract() -> dict[str, Any]:
    return {
        "schema_version": None,
        "snapshot_status": "legacy_unversioned",
        "report_template_version": None,
        "decision_criteria_version": None,
    }
