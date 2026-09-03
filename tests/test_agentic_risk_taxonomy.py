from backend.agentic_risk_taxonomy import (
    FRAMEWORK_COMMIT,
    MAPPING_VERSION,
    enrich_risk_codes,
    map_risk_codes,
)


def test_exact_platform_codes_map_to_pinned_owasp_agentic_categories():
    mapping = map_risk_codes(
        [
            "agent_goal_hijack",
            "mcp_tool_description_injection",
            "mcp_schema_drift",
            "runtime.command_execution",
        ]
    )

    assert mapping["risk_codes"] == ["ASI01", "ASI04", "ASI05"]
    assert mapping["status"] == "mapped"
    assert mapping["mapping_version"] == MAPPING_VERSION
    assert mapping["framework_commit"] == FRAMEWORK_COMMIT
    assert mapping["categories"][0]["title_en"] == "Agent Behaviour Hijack"


def test_unknown_codes_remain_unmapped_and_mixed_input_is_partial():
    unknown = map_risk_codes(["future_upstream_risk"])
    assert unknown["risk_codes"] == []
    assert unknown["status"] == "unmapped"

    enriched, partial = enrich_risk_codes(["runtime.goal_drift_detected", "future_runtime_signal"])
    assert enriched == ["runtime.goal_drift_detected", "future_runtime_signal", "ASI01"]
    assert partial["status"] == "partial"


def test_only_valid_exact_asi_codes_are_accepted():
    enriched, mapping = enrich_risk_codes(["asi01", "ASI10", "ASI11", "ASI01-looking-text"])
    assert enriched == ["asi01", "ASI10", "ASI11", "ASI01-looking-text", "ASI01"]
    assert mapping["risk_codes"] == ["ASI01", "ASI10"]
    assert mapping["status"] == "partial"
