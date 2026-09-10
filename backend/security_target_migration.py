from __future__ import annotations

from sqlalchemy.engine import Connection


MIGRATION_NAME = "agent_security_target_classification_v1"


def migrate_security_target_classification(connection: Connection) -> None:
    """Add and backfill asset/connector classification without replacing legacy data."""

    columns = {
        row[1]
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(security_targets)"
        ).fetchall()
    }
    if not columns:
        return

    if "asset_type" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE security_targets "
            "ADD COLUMN asset_type VARCHAR(32) NOT NULL DEFAULT 'agent'"
        )
    if "connector_type" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE security_targets "
            "ADD COLUMN connector_type VARCHAR(64) NOT NULL DEFAULT 'custom_http'"
        )

    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS backend_schema_migrations "
        "(name VARCHAR(128) PRIMARY KEY, applied_at DATETIME NOT NULL)"
    )
    migration = connection.exec_driver_sql(
        "SELECT name FROM backend_schema_migrations WHERE name = ?",
        (MIGRATION_NAME,),
    ).first()
    if not migration:
        connection.exec_driver_sql(
            "UPDATE security_targets SET asset_type = "
            "CASE WHEN target_type = 'mcp_gateway' THEN 'mcp' ELSE 'agent' END"
        )
        connection.exec_driver_sql(
            "UPDATE security_targets SET connector_type = CASE "
            "WHEN target_type = 'mcp_gateway' THEN 'mcp_gateway' "
            "WHEN target_type = 'dify' THEN 'dify' "
            "WHEN target_type IN ('coze', 'coze-com') THEN 'coze' "
            "WHEN target_type = 'http' THEN 'custom_http' "
            "WHEN target_type = 'websocket' THEN 'websocket' "
            "ELSE 'openai_compatible' END"
        )
        connection.exec_driver_sql(
            "INSERT INTO backend_schema_migrations (name, applied_at) "
            "VALUES (?, CURRENT_TIMESTAMP)",
            (MIGRATION_NAME,),
        )

    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_security_targets_asset_type "
        "ON security_targets (asset_type)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_security_targets_connector_type "
        "ON security_targets (connector_type)"
    )
