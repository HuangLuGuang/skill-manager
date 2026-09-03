from collections import Counter

from backend.tc260_coverage import build_tc260_coverage_profile


def test_tc260_profile_uses_pinned_technical_document_without_claiming_national_standard():
    profile = build_tc260_coverage_profile()
    assert profile["schema_version"] == "tc260-coverage@1"
    assert profile["source"] == {
        "document_id": "TC260-003",
        "document_title": "生成式人工智能服务安全基本要求",
        "published_at": "2024-02-29",
        "document_type": "tc260_technical_document",
        "is_national_standard": False,
        "url": "https://www.tc260.org.cn/upload/2024-03-01/1709282398070082466.pdf",
        "sha256": "6c681bb7e5bf0a5c9c37ab1a66ee20662f37c1ee3efd98034c9742405488f0e4",
        "mapped_section": "appendix_a_normative",
    }


def test_tc260_profile_maps_the_exact_five_categories_and_thirty_one_appendix_risks():
    profile = build_tc260_coverage_profile()
    assert profile["catalog"]["category_count"] == 5
    assert profile["catalog"]["control_count"] == 31
    assert profile["catalog"]["risk_counts_by_category"] == {
        "core_socialist_values": 8,
        "discrimination": 9,
        "commercial_illegal": 5,
        "rights_infringement": 7,
        "high_safety_service_failure": 2,
    }
    assert profile["summary"]["coverage_percentage"] is None


def test_tc260_coverage_statuses_require_evidence_or_an_explicit_gap():
    profile = build_tc260_coverage_profile()
    controls = profile["controls"]
    assert len(controls) == 31
    counts = Counter(item["coverage_status"] for item in controls)
    assert counts == {"uncovered": 24, "partial": 7}
    assert profile["summary"] == {"verified": 0, "partial": 7, "uncovered": 24, "total": 31, "coverage_percentage": None}

    for item in controls:
        assert item["target_assessment_status"] == "unverified"
        assert item["target_evidence_refs"] == []
        if item["coverage_status"] == "partial":
            assert item["evidence_refs"]
            assert item["limitations"]
            assert item["gap_code"] is None
        else:
            assert item["evidence_refs"] == []
            assert item["gap_code"]


def test_tc260_profile_builds_independent_snapshots():
    first = build_tc260_coverage_profile()
    first["controls"][0]["coverage_status"] = "verified"
    assert build_tc260_coverage_profile()["controls"][0]["coverage_status"] == "uncovered"
