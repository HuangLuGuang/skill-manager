from __future__ import annotations

from copy import deepcopy
from typing import Any

TC260_COVERAGE_SCHEMA_VERSION = "tc260-coverage@1"
TC260_PROFILE_VERSION = "TC260-003-2024-02-29@1"
TC260_SOURCE_URL = "https://www.tc260.org.cn/upload/2024-03-01/1709282398070082466.pdf"
TC260_SOURCE_SHA256 = "6c681bb7e5bf0a5c9c37ab1a66ee20662f37c1ee3efd98034c9742405488f0e4"

_CATEGORIES = [
    "core_socialist_values",
    "discrimination",
    "commercial_illegal",
    "rights_infringement",
    "high_safety_service_failure",
]

_CONTROLS = [
    ("A.1.a", "core_socialist_values", "subvert_state_power"),
    ("A.1.b", "core_socialist_values", "harm_national_security_or_image"),
    ("A.1.c", "core_socialist_values", "separatism_or_social_instability"),
    ("A.1.d", "core_socialist_values", "terrorism_or_extremism"),
    ("A.1.e", "core_socialist_values", "ethnic_hatred"),
    ("A.1.f", "core_socialist_values", "violence_or_obscenity"),
    ("A.1.g", "core_socialist_values", "false_harmful_information"),
    ("A.1.h", "core_socialist_values", "other_prohibited_content"),
    ("A.2.a", "discrimination", "ethnic_discrimination"),
    ("A.2.b", "discrimination", "belief_discrimination"),
    ("A.2.c", "discrimination", "nationality_discrimination"),
    ("A.2.d", "discrimination", "regional_discrimination"),
    ("A.2.e", "discrimination", "gender_discrimination"),
    ("A.2.f", "discrimination", "age_discrimination"),
    ("A.2.g", "discrimination", "occupation_discrimination"),
    ("A.2.h", "discrimination", "health_discrimination"),
    ("A.2.i", "discrimination", "other_discrimination"),
    ("A.3.a", "commercial_illegal", "intellectual_property_infringement"),
    ("A.3.b", "commercial_illegal", "business_ethics_violation"),
    ("A.3.c", "commercial_illegal", "trade_secret_disclosure"),
    ("A.3.d", "commercial_illegal", "monopoly_or_unfair_competition"),
    ("A.3.e", "commercial_illegal", "other_commercial_violation"),
    ("A.4.a", "rights_infringement", "physical_or_mental_harm"),
    ("A.4.b", "rights_infringement", "portrait_right_infringement"),
    ("A.4.c", "rights_infringement", "reputation_right_infringement"),
    ("A.4.d", "rights_infringement", "honor_right_infringement"),
    ("A.4.e", "rights_infringement", "privacy_right_infringement"),
    ("A.4.f", "rights_infringement", "personal_information_infringement"),
    ("A.4.g", "rights_infringement", "other_legal_rights_infringement"),
    ("A.5.a", "high_safety_service_failure", "inaccurate_high_safety_content"),
    ("A.5.b", "high_safety_service_failure", "unreliable_high_safety_content"),
]

_PARTIAL = {
    "A.1.g": (
        ["human_agent_trust_exploit_detection"],
        ["backend/security_scan_controls.py", "services/agent-security-worker/aig_adapter.py"],
        "agent_deception_signals_do_not_cover_all_false_harmful_content",
    ),
    "A.3.c": (
        ["data_leakage_detection"],
        ["backend/security_scan_controls.py", "services/agent-security-worker/aig_adapter.py"],
        "generic_data_leakage_is_not_trade_secret_classification",
    ),
    "A.4.a": (
        ["human_agent_trust_exploit_detection"],
        ["backend/security_scan_controls.py", "services/agent-security-worker/aig_adapter.py"],
        "trust_exploitation_does_not_cover_all_physical_or_mental_harm",
    ),
    "A.4.e": (
        ["data_leakage_detection", "privacy_gateway"],
        ["backend/security_scan_controls.py", "backend/routers/llm_gateway.py"],
        "privacy_leakage_signals_do_not_assess_all_privacy_rights",
    ),
    "A.4.f": (
        ["data_leakage_detection", "pii_detection"],
        ["backend/security_scan_controls.py", "backend/routers/llm_gateway.py"],
        "pii_detection_does_not_assess_lawful_personal_information_processing",
    ),
    "A.5.a": (
        ["cascading_failure_detection", "human_agent_trust_exploit_detection"],
        ["backend/security_scan_controls.py", "services/agent-security-worker/aig_adapter.py"],
        "agent_failure_signals_do_not_measure_domain_factual_accuracy",
    ),
    "A.5.b": (
        ["cascading_failure_detection", "human_agent_trust_exploit_detection"],
        ["backend/security_scan_controls.py", "services/agent-security-worker/aig_adapter.py"],
        "agent_failure_signals_do_not_measure_domain_helpfulness_or_reliability",
    ),
}


def build_tc260_coverage_profile() -> dict[str, Any]:
    controls: list[dict[str, Any]] = []
    for control_id, category, title_code in _CONTROLS:
        base: dict[str, Any] = {
            "control_id": control_id,
            "category": category,
            "title_code": title_code,
            "target_assessment_status": "unverified",
            "target_evidence_refs": [],
        }
        if control_id in _PARTIAL:
            capability_codes, evidence_refs, limitation = _PARTIAL[control_id]
            base.update(
                {
                    "coverage_status": "partial",
                    "capability_codes": capability_codes,
                    "evidence_refs": evidence_refs,
                    "verification_scope": "agent_scan_or_gateway_signal_only",
                    "limitations": [limitation],
                    "gap_code": None,
                }
            )
        else:
            base.update(
                {
                    "coverage_status": "uncovered",
                    "capability_codes": [],
                    "evidence_refs": [],
                    "verification_scope": None,
                    "limitations": [],
                    "gap_code": "tc260_content_safety_evaluator_not_integrated",
                }
            )
        controls.append(base)

    counts = {
        status: sum(item["coverage_status"] == status for item in controls)
        for status in ("verified", "partial", "uncovered")
    }
    return deepcopy(
        {
            "schema_version": TC260_COVERAGE_SCHEMA_VERSION,
            "profile_version": TC260_PROFILE_VERSION,
            "source": {
                "document_id": "TC260-003",
                "document_title": "生成式人工智能服务安全基本要求",
                "published_at": "2024-02-29",
                "document_type": "tc260_technical_document",
                "is_national_standard": False,
                "url": TC260_SOURCE_URL,
                "sha256": TC260_SOURCE_SHA256,
                "mapped_section": "appendix_a_normative",
            },
            "catalog": {
                "category_count": len(_CATEGORIES),
                "control_count": len(_CONTROLS),
                "categories": list(_CATEGORIES),
                "risk_counts_by_category": {
                    category: sum(item[1] == category for item in _CONTROLS) for category in _CATEGORIES
                },
            },
            "controls": controls,
            "summary": {**counts, "total": len(controls), "coverage_percentage": None},
            "interpretation": {
                "coverage_status_subject": "current_agent_manager_platform_capability",
                "target_assessment_default": "unverified",
                "no_percentage_reason": "verified_coverage_requires_tc260_content_safety_evaluator_and_test_evidence",
                "agent_scan_is_not_tc260_content_safety_evaluation": True,
            },
        }
    )
