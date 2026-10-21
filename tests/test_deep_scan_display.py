"""Regression contracts for deep scan translations and original evidence."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent_manager.core.deep_scan_display import with_deep_scan_analysis_display, with_deep_scan_display
from agent_manager.core.skillspector import _normalize_raw_findings


def finding(rule="TP2", **changes):
    return {"source": "skillspector", "rule": rule, "title": rule, "message": rule, **changes}


@pytest.mark.parametrize(("explanation", "remediation", "subtype"), [
    (
        "Mixing characters from multiple Unicode scripts in a single identifier is a common technique to create visually ambiguous tool names.",
        "Restrict identifier fields to a single Unicode script. Prefer ASCII-only identifiers.",
        "mixed_script",
    ),
    (
        "Confusable Unicode characters (e.g., Cyrillic or Greek lookalikes of Latin letters) can make a malicious tool name appear identical to a trusted one.",
        "Replace all non-ASCII characters in identifier fields with their ASCII equivalents. Use a Unicode normalization/confusables check in CI.",
        "homoglyph",
    ),
    (
        "RTL override characters (U+202E, U+202D, U+2066-U+2069) can reverse text rendering to make malicious content appear benign.",
        "Remove all directional override Unicode characters from metadata fields.",
        "direction",
    ),
    (
        "Invisible Unicode formatting characters (soft hyphen U+00AD, CGJ U+034F, word joiner U+2060) inserted into identifiers create visually identical but technically different names.",
        "Strip invisible formatting characters (U+00AD, U+034F, U+2060) from all identifier fields.",
        "invisible",
    ),
])
def test_tp2_subtypes_keep_their_own_explanation_and_advice(explanation, remediation, subtype):
    original = finding(explanation=explanation, remediation=remediation, severity="HIGH", evidence="raw\n样本")
    before = deepcopy(original)
    result = with_deep_scan_display(original)
    assert result["display"]["title"]["code"] == "TP2_name"
    assert result["display"]["explanation"]["code"] == f"TP2_{subtype}_explanation"
    assert result["display"]["remediation"]["code"] == f"TP2_{subtype}_remediation"
    assert {k: v for k, v in result.items() if k != "display"} == before
    assert original == before


def test_dynamic_identifiers_paths_and_multiline_evidence_are_preserved():
    path = "目录/it's-a-file.py\nsecond line"
    original = finding("LP1", message=f"Code capability 'network' detected in {path} but not covered by declared permissions.")
    display = with_deep_scan_display(original)["display"]["message"]
    assert display == {"code": "LP1_underdeclared_message", "params": {"p0": "network", "p1": path}}


def test_custom_text_and_unknown_sources_are_not_replaced_by_rule_defaults():
    original = finding(message="  Custom LLM output\n中文原文  ", explanation="custom explanation", remediation="custom advice")
    result = with_deep_scan_display(original)
    assert "message" not in result["display"]
    assert "explanation" not in result["display"]
    assert "remediation" not in result["display"]
    assert result["message"] == original["message"]
    for source in ("third-party", None):
        other = {**original, "source": source}
        assert with_deep_scan_display(other) == other
    assert with_deep_scan_display(finding("NEW_RULE"))["display"] == {}


def test_complete_templates_only_and_rule_and_source_must_match():
    advice = "Restrict identifier fields to a single Unicode script. Prefer ASCII-only identifiers."
    for item in (
        finding(remediation=advice + " Extra upstream advice."),
        finding("TP1", remediation=advice),
        finding(source="agent-manager-local", remediation=advice),
        finding(remediation=" " + advice),
    ):
        assert "remediation" not in with_deep_scan_display(item)["display"]


def test_local_tp2_does_not_inherit_external_mixed_script_meaning():
    original = finding(source="agent-manager-local", title="Unicode 欺骗字符", message="元数据中包含方向覆盖或零宽字符，可能隐藏真实内容。 文件: SKILL.md:7")
    result = with_deep_scan_display(original)
    assert "rule" not in result["display"]
    assert result["display"]["message"]["code"] == "TP2_local_message"
    assert result["display"]["message"]["params"] == {"p0": "SKILL.md:7"}


def test_historical_api_response_is_enriched_without_mutating_saved_report():
    from agent_manager.api.router import get_scan_report

    report = {"skillspector_analysis": {"findings": [finding(explanation="Mixing characters from multiple Unicode scripts in a single identifier is a common technique to create visually ambiguous tool names.")], "risk_severity": "HIGH", "risk_score": 25}}
    before = deepcopy(report)
    entry = SimpleNamespace(vetting=SimpleNamespace(scan_report=report, policy_notes=[]), family_id="family", skill_id="v1", version_no=1, name="sample")
    mgr = SimpleNamespace(get_skill=lambda _: entry)
    response = get_scan_report("family", mgr)
    assert response["scan_report"]["skillspector_analysis"]["findings"][0]["display"]["explanation"]["code"] == "TP2_mixed_script_explanation"
    assert report == before
    assert response["scan_report"]["skillspector_analysis"]["risk_severity"] == "HIGH"
    assert response["scan_report"]["skillspector_analysis"]["risk_score"] == 25


def test_new_report_normalization_and_historical_read_use_same_metadata():
    raw = {"findings": [{"rule_id": "TP2", "explanation": "Mixing characters from multiple Unicode scripts in a single identifier is a common technique to create visually ambiguous tool names.", "remediation": "Restrict identifier fields to a single Unicode script. Prefer ASCII-only identifiers.", "severity": "HIGH"}]}
    normalized = _normalize_raw_findings(raw)[0]
    assert normalized["message"] == "TP2"
    assert normalized["display"]["remediation"]["code"] == "TP2_mixed_script_remediation"
    assert with_deep_scan_analysis_display({"findings": [normalized]})["findings"][0] == normalized


@pytest.mark.parametrize(("rule", "message", "code", "params"), [
    ("AST8", "Dangerous chain: exec() wrapping requests.get", "AST8_chain_exec", {"p0": "requests.get"}),
    ("TT3", "Tainted flow: 'secret' from os.getenv (line 12, environment) → requests.post (network)", "TT3_tainted_flow", {"p0": "secret", "p1": "os.getenv", "p2": "12", "p3": "environment", "p4": "requests.post", "p5": "network"}),
    ("SC4", "Known Vulnerable Dependency: example==1.0 — 2 advisory(ies): CVE-example", "SC4_advisories", {"p0": "example==1.0", "p1": "2", "p2": "CVE-example"}),
    ("TR2", "Shadow Command Trigger: '/help' conflicts with built-in command 'help'", "TR2_shadow", {"p0": "/help", "p1": "help"}),
    ("TP3", "Excessive parameter description length for 'query': 1100 chars (limit: 1000).", "TP3_length_message", {"p0": "query", "p1": "1100", "p2": "1000"}),
])
def test_other_analyzer_templates_preserve_parameters(rule, message, code, params):
    assert with_deep_scan_display(finding(rule, message=message))["display"]["message"] == {"code": code, "params": params}


def test_taint_category_labels_translate_without_changing_evidence_parameters():
    message = "Direct flow: os.getenv (credential/environment) → requests.post (network output)"
    result = with_deep_scan_display(finding("TT3", message=message))["display"]["message"]
    assert result["params"] == {"p0": "os.getenv", "p1": "credential/environment", "p2": "requests.post", "p3": "network output"}
    assert result["param_codes"] == {"p1": "taint_credential_environment", "p3": "taint_network_output"}


def test_evidence_equal_to_a_known_phrase_stays_original():
    result = _normalize_raw_findings({"findings": [{"rule_id": "E1", "finding": "External Transmission"}]})[0]
    assert result["message"] == result["finding"] == "External Transmission"
    assert "message" not in result["display"]


@pytest.mark.parametrize("source", [[], {}])
def test_historical_unknown_source_shapes_stay_original(source):
    original = finding(source=source)
    assert with_deep_scan_display(original) == original
