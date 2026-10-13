"""Agent-level MCP grants shared by registration, credential issuance and runtime."""
import json

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from . import models
from .api_errors import ApiError

MCP_SCOPES = {"mcp:connect", "mcp:list-tools", "mcp:call-tools"}


def gateway_names(value: str | None) -> list[str]:
    return json.loads(value or "[]")


def validate_agent_gateways(db: Session, names: list[str], *, previous=()) -> list[str]:
    names = list(dict.fromkeys(name.strip() for name in names if name.strip()))
    active = {row.slug for row in db.query(models.McpGateway).filter_by(status="active").all()}
    if set(names) - active - set(previous):
        raise ApiError(422, "agent.mcp_gateway_unavailable",
                       "请选择已启用的 MCP 网关；已失效的原有选择可保留或移除",
                       "Select active MCP gateways; existing unavailable selections may be kept or removed")
    return names


def ensure_agent_mcp_scope(db: Session, token: models.AccessToken, gateways: list[str]) -> None:
    if token.token_type != "agent_runtime":
        return
    agent = db.query(models.ManagedAgent).filter_by(agent_id=token.bound_agent_id).first()
    if not agent:
        raise ApiError(403, "agent.not_found", "智能体不存在", "Agent not found")
    if agent.status != "active":
        raise ApiError(403, "agent.disabled", "智能体未启用", "Agent is disabled")
    if set(gateways) - set(gateway_names(agent.allowed_mcp_gateways_json)):
        raise ApiError(403, "agent.mcp_scope_exceeded",
                       "MCP 网关超出智能体允许范围，请先修改智能体的 MCP 工具访问配置",
                       "MCP gateways exceed the Agent's allowed scope. Update the Agent's MCP tool access first")


def migrate_agent_mcp_scope(engine: Engine) -> None:
    """Backfill once from active, unexpired Agent credentials without widening them."""
    with engine.begin() as conn:
        # SQLite DDL and the backfill must commit together, including on startup retries.
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        audit_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mcp_call_audits)")}
        if audit_columns and "bound_agent_id" not in audit_columns:
            conn.exec_driver_sql("ALTER TABLE mcp_call_audits ADD COLUMN bound_agent_id VARCHAR(128)")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_mcp_call_audits_bound_agent_id ON mcp_call_audits(bound_agent_id)")
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(managed_agents)")}
        if "allowed_mcp_gateways_json" in columns:
            return
        conn.exec_driver_sql("ALTER TABLE managed_agents ADD COLUMN allowed_mcp_gateways_json TEXT NOT NULL DEFAULT '[]'")
        rows = conn.exec_driver_sql(
            "SELECT bound_agent_id, allowed_mcp_gateways_json, scopes_json FROM access_tokens "
            "WHERE token_type = 'agent_runtime' AND status = 'active' "
            "AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)"
        )
        grants = {}
        for agent_id, gateways, scopes in rows:
            if MCP_SCOPES.intersection(gateway_names(scopes)):
                grants.setdefault(agent_id, set()).update(gateway_names(gateways))
        for agent_id, names in grants.items():
            conn.exec_driver_sql(
                "UPDATE managed_agents SET allowed_mcp_gateways_json = ? WHERE agent_id = ?",
                (json.dumps(sorted(names)), agent_id),
            )
