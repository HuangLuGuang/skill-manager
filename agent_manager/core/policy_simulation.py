"""Read-only policy calculations from user-selected, synthetic analyzer findings."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import RiskLevel
from .policy import CompanyPolicy, DEFAULT_RISK_CLASSIFICATION
from .vetting import _classify_findings, _risk_from_classification, _risk_max_severity, reconcile_llm_risk


FindingKind = Literal[
    "data_exfiltration", "supply_chain", "prompt_injection", "tool_misuse", "network",
    "credential_access", "dynamic_execution", "excessive_permissions",
    "documented_external_api", "dependency", "runtime",
]
AnalyzerStatus = Literal["completed", "disabled", "skipped", "unavailable", "failed"]
Permission = Annotated[str, Field(min_length=1, max_length=100)]


class SimulationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimulationFinding(SimulationModel):
    kind: FindingKind
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


class SimulationAnalyzer(SimulationModel):
    status: AnalyzerStatus
    findings: list[SimulationFinding] = Field(default_factory=list, max_length=10)


class SimulationLlm(SimulationModel):
    status: AnalyzerStatus
    risk: RiskLevel | None = None

    @model_validator(mode="after")
    def completed_has_risk(self):
        if self.status == "completed" and self.risk is None:
            raise ValueError("Completed LLM analysis requires a risk conclusion")
        return self


class SimulationPolicy(SimulationModel):
    judgement_mode: Literal["strict", "balanced", "permissive"] = "balanced"
    risk_classification: dict[FindingKind, Literal["blocking", "risk", "noise"]] = Field(
        default_factory=lambda: dict(DEFAULT_RISK_CLASSIFICATION),
    )
    auto_approve_risk: list[RiskLevel] = Field(default_factory=lambda: [RiskLevel.BENIGN], max_length=3)
    require_human_review: list[RiskLevel] = Field(default_factory=lambda: [RiskLevel.SUSPICIOUS], max_length=3)
    auto_reject_risk: list[RiskLevel] = Field(default_factory=lambda: [RiskLevel.MALICIOUS], max_length=3)
    require_sandbox_for_risk: list[RiskLevel] = Field(default_factory=lambda: [RiskLevel.SUSPICIOUS, RiskLevel.MALICIOUS], max_length=3)
    blocked_permissions: list[Permission] = Field(default_factory=list, max_length=100)


class PolicySimulationRequest(SimulationModel):
    policy: SimulationPolicy
    rules: SimulationAnalyzer
    deep: SimulationAnalyzer
    sandbox: SimulationAnalyzer
    llm: SimulationLlm
    declared_permissions: list[Permission] = Field(default_factory=list, max_length=100)


# Canonical examples use the same rule/category recognition as scanner findings.
_FINDING_EXAMPLES = {
    "data_exfiltration": {"rule": "data_exfiltration"},
    "supply_chain": {"rule": "download_and_execute"},
    "prompt_injection": {"category": "prompt injection"},
    "tool_misuse": {"category": "tool misuse"},
    "network": {"category": "network"},
    "credential_access": {"rule": "credential_file_access"},
    "dynamic_execution": {"rule": "dynamic_code_execution"},
    "excessive_permissions": {"rule": "tool_not_in_allowlist"},
    "documented_external_api": {"rule": "e1", "file": "SKILL.md", "message": "curl https://example.invalid/api"},
    "dependency": {"rule": "dependency_missing"},
    "runtime": {"category": "runtime"},
}


def simulate_policy(body: PolicySimulationRequest) -> dict:
    policy = CompanyPolicy(body.policy.model_dump(mode="json"))
    findings = []
    for source in ("rules", "deep", "sandbox"):
        analyzer = getattr(body, source)
        if analyzer.status == "completed":
            findings.extend({
                **_FINDING_EXAMPLES[finding.kind], "severity": finding.severity,
                "source": source, "kind": finding.kind, "id": f"{source}:{index}",
            } for index, finding in enumerate(analyzer.findings))

    interim_risk = RiskLevel.from_severity(_risk_max_severity([
        finding for finding in findings if finding["source"] != "sandbox"
    ]))
    classification = _classify_findings(findings, policy)
    tool_risk, tool_reason = _risk_from_classification(classification, policy.judgement_mode)
    blocking = bool(classification["blocking_count"])
    llm_risk = body.llm.risk if body.llm.status == "completed" else None
    final_risk, lowered, downgrade_blocked = reconcile_llm_risk(
        tool_risk, llm_risk, blocking, policy.judgement_mode,
    )
    llm_reason = body.llm.status
    if llm_risk:
        llm_reason = (
            "blocked_by_finding" if downgrade_blocked and blocking
            else "blocked_by_mode" if downgrade_blocked
            else "lowered" if lowered
            else "raised" if final_risk != tool_risk
            else "unchanged"
        )
    violations = policy.check_tool_declarations(body.declared_permissions)
    permission_blocked = any(violation.blocking for violation in violations)
    status = policy.decide(final_risk, violations)
    states = {source: getattr(body, source).status for source in ("rules", "deep", "sandbox", "llm")}
    completed_count = sum(state == "completed" for state in states.values())
    return {
        "simulation": True,
        "judgement_mode": policy.judgement_mode,
        "analyzer_states": states,
        "coverage": "none" if not completed_count else "complete" if completed_count == 4 else "partial",
        "findings": [{key: item[key] for key in ("id", "source", "kind", "severity", "classification")} for item in classification["items"]],
        "counts": {key: classification[f"{key}_count"] for key in ("blocking", "risk", "noise")},
        "interim_risk": interim_risk.value,
        "sandbox_required": policy.requires_sandbox(interim_risk),
        "tool_risk": tool_risk.value,
        "tool_reason": tool_reason,
        "llm_risk": llm_risk.value if llm_risk else None,
        "llm_reason": llm_reason,
        "final_risk": final_risk.value,
        "admission_status": status.value,
        "admission_reason": "blocked_permission" if permission_blocked else "risk_action",
    }
