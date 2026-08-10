from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from agent_manager.core.manager import AgentManager

from . import models


SKILL_CONTEXT_MISSING = "gateway.skill_context_missing"
SKILL_UNKNOWN = "gateway.skill_unknown"
SKILL_ID_MISMATCH = "gateway.skill_id_mismatch"
SKILL_NAME_MISMATCH = "gateway.skill_name_mismatch"
SKILL_NOT_LOADABLE = "gateway.skill_not_loadable"
SKILL_NOT_ALLOWED = "gateway.skill_not_allowed_for_agent"
SKILL_CONTEXT_UNVERIFIED = "gateway.skill_context_unverified"


def _clean(value: Any, max_length: int = 255) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    result = str(value).strip()
    return result[:max_length] if result else None


def declared_skill_context(metadata: dict[str, Any] | None) -> dict[str, str | None]:
    values = metadata if isinstance(metadata, dict) else {}
    nested = values.get("agent_manager") if isinstance(values.get("agent_manager"), dict) else {}

    def value(flat_key: str, nested_key: str) -> str | None:
        return _clean(values.get(flat_key) if flat_key in values else nested.get(nested_key))

    return {
        "skill_id": value("agent_manager_skill_id", "skill_id"),
        "skill_version_id": value("agent_manager_skill_version_id", "skill_version_id"),
        "skill_name": value("agent_manager_skill_name", "skill_name"),
    }


@dataclass(frozen=True)
class GatewaySkillAssessment:
    skill_id: str | None = None
    skill_version_id: str | None = None
    skill_name: str | None = None
    skill_context_source: str | None = None
    skill_trust_state: str | None = None
    skill_alert_severity: str | None = None
    skill_alert_codes: list[str] = field(default_factory=list)

    def audit_fields(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_version_id": self.skill_version_id,
            "skill_name": self.skill_name,
            "skill_context_source": self.skill_context_source,
            "skill_trust_state": self.skill_trust_state,
            "skill_alert_severity": self.skill_alert_severity,
            "skill_alert_codes_json": json.dumps(self.skill_alert_codes, ensure_ascii=False),
        }

    def trace_fields(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_version_id": self.skill_version_id,
            "skill_name": self.skill_name,
            "skill_context_source": self.skill_context_source,
            "skill_trust_state": self.skill_trust_state,
            "skill_alert_severity": self.skill_alert_severity,
            "skill_alert_codes": list(self.skill_alert_codes),
        }


def evaluate_gateway_skill_context(
    db: Session,
    token: models.AccessToken | models.LlmApiKey,
    metadata: dict[str, Any] | None,
    *,
    manager: AgentManager | None,
    source: str,
) -> GatewaySkillAssessment:
    declared = declared_skill_context(metadata)
    has_context = any(declared.values())
    is_agent_credential = isinstance(token, models.AccessToken) and token.token_type == "agent_runtime"

    if not has_context:
        if is_agent_credential:
            return GatewaySkillAssessment(
                skill_context_source="missing",
                skill_trust_state="missing",
                skill_alert_severity="info",
                skill_alert_codes=[SKILL_CONTEXT_MISSING],
            )
        return GatewaySkillAssessment()

    identifier = declared["skill_version_id"] or declared["skill_id"] or declared["skill_name"]
    entry = manager.get_skill(identifier) if manager and identifier else None
    if not entry:
        return GatewaySkillAssessment(
            skill_id=declared["skill_id"],
            skill_version_id=declared["skill_version_id"],
            skill_name=declared["skill_name"],
            skill_context_source=source,
            skill_trust_state="suspicious",
            skill_alert_severity="high",
            skill_alert_codes=[SKILL_UNKNOWN],
        )

    family_id = entry.family_id or entry.skill_id
    alerts: list[str] = []
    if (
        (declared["skill_version_id"] and declared["skill_version_id"] != entry.skill_id)
        or (declared["skill_id"] and declared["skill_id"] != family_id)
    ):
        alerts.append(SKILL_ID_MISMATCH)
    if declared["skill_name"] and declared["skill_name"] != entry.name:
        alerts.append(SKILL_NAME_MISMATCH)
    if not entry.is_loadable():
        alerts.append(SKILL_NOT_LOADABLE)

    if is_agent_credential and token.bound_agent_id:
        agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == token.bound_agent_id).first()
        allowed = set()
        if agent:
            try:
                values = json.loads(agent.skill_names_json or "[]")
                allowed = {str(item) for item in values if str(item).strip()} if isinstance(values, list) else set()
            except json.JSONDecodeError:
                allowed = set()
        if not agent or not ({entry.name, entry.skill_id, family_id} & allowed):
            alerts.append(SKILL_NOT_ALLOWED)

    if alerts:
        return GatewaySkillAssessment(
            skill_id=family_id,
            skill_version_id=entry.skill_id,
            skill_name=declared["skill_name"] or entry.name,
            skill_context_source=source,
            skill_trust_state="suspicious",
            skill_alert_severity="high",
            skill_alert_codes=alerts,
        )

    return GatewaySkillAssessment(
        skill_id=family_id,
        skill_version_id=entry.skill_id,
        skill_name=entry.name,
        skill_context_source=source,
        skill_trust_state="declared_trusted",
        skill_alert_severity="medium",
        skill_alert_codes=[SKILL_CONTEXT_UNVERIFIED],
    )
