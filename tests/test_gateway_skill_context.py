from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.gateway_skill_context import (
    SKILL_CONTEXT_MISSING,
    SKILL_CONTEXT_UNVERIFIED,
    SKILL_ID_MISMATCH,
    SKILL_NAME_MISMATCH,
    SKILL_NOT_ALLOWED,
    SKILL_NOT_LOADABLE,
    SKILL_UNKNOWN,
    evaluate_gateway_skill_context,
)
from backend.sqlite_db import Base


class _Manager:
    def __init__(self, entry=None):
        self.entry = entry

    def get_skill(self, identifier):
        if not self.entry:
            return None
        valid = {self.entry.skill_id, self.entry.family_id, self.entry.name}
        return self.entry if identifier in valid else None


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'skill-context.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _entry(*, loadable=True):
    return SimpleNamespace(
        skill_id="skill-version-1",
        family_id="skill-family-1",
        name="approved-skill",
        is_loadable=lambda: loadable,
    )


def test_agent_request_without_skill_context_is_recorded_as_missing(tmp_path):
    db = _session(tmp_path)
    token = models.AccessToken(token_type="agent_runtime", bound_agent_id="risk-agent")

    result = evaluate_gateway_skill_context(db, token, {}, manager=None, source="caller_metadata")

    assert result.skill_trust_state == "missing"
    assert result.skill_alert_severity == "info"
    assert result.skill_alert_codes == [SKILL_CONTEXT_MISSING]


def test_declared_skill_matches_registry_and_agent_but_remains_unverified(tmp_path):
    db = _session(tmp_path)
    db.add(models.ManagedAgent(agent_id="risk-agent", name="Risk", skill_names_json='["skill-family-1"]'))
    db.commit()
    token = models.AccessToken(token_type="agent_runtime", bound_agent_id="risk-agent")

    result = evaluate_gateway_skill_context(
        db,
        token,
        {
            "agent_manager_skill_id": "skill-family-1",
            "agent_manager_skill_version_id": "skill-version-1",
            "agent_manager_skill_name": "approved-skill",
        },
        manager=_Manager(_entry()),
        source="caller_metadata",
    )

    assert result.skill_trust_state == "declared_trusted"
    assert result.skill_alert_severity == "medium"
    assert result.skill_alert_codes == [SKILL_CONTEXT_UNVERIFIED]


def test_unknown_and_mismatched_skill_declarations_are_suspicious(tmp_path):
    db = _session(tmp_path)
    token = models.AccessToken(token_type="mcp_gateway")

    unknown = evaluate_gateway_skill_context(
        db,
        token,
        {"agent_manager_skill_name": "unknown"},
        manager=_Manager(),
        source="mcp_meta",
    )
    assert unknown.skill_alert_codes == [SKILL_UNKNOWN]
    assert unknown.skill_trust_state == "suspicious"

    mismatch = evaluate_gateway_skill_context(
        db,
        token,
        {"agent_manager_skill_id": "skill-family-1", "agent_manager_skill_name": "forged-name"},
        manager=_Manager(_entry()),
        source="mcp_meta",
    )
    assert mismatch.skill_alert_codes == [SKILL_NAME_MISMATCH]

    id_mismatch = evaluate_gateway_skill_context(
        db,
        token,
        {
            "agent_manager_skill_id": "different-family",
            "agent_manager_skill_version_id": "skill-version-1",
            "agent_manager_skill_name": "approved-skill",
        },
        manager=_Manager(_entry()),
        source="mcp_meta",
    )
    assert id_mismatch.skill_alert_codes == [SKILL_ID_MISMATCH]
    assert id_mismatch.skill_trust_state == "suspicious"


def test_non_loadable_or_unassigned_skill_is_suspicious(tmp_path):
    db = _session(tmp_path)
    db.add(models.ManagedAgent(agent_id="risk-agent", name="Risk", skill_names_json="[]"))
    db.commit()
    token = models.AccessToken(token_type="agent_runtime", bound_agent_id="risk-agent")

    result = evaluate_gateway_skill_context(
        db,
        token,
        {"agent_manager_skill_id": "skill-family-1"},
        manager=_Manager(_entry(loadable=False)),
        source="caller_metadata",
    )

    assert result.skill_trust_state == "suspicious"
    assert result.skill_alert_severity == "high"
    assert result.skill_alert_codes == [SKILL_NOT_LOADABLE, SKILL_NOT_ALLOWED]
