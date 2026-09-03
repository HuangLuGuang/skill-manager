from __future__ import annotations

from sqlalchemy.engine import Connection


MIGRATION_NAME = "dify_asset_inventory_v1"


def migrate_dify_asset_inventory(connection: Connection) -> None:
    credential_columns = {
        row[1] for row in connection.exec_driver_sql("PRAGMA table_info(security_target_credentials)").fetchall()
    }
    if credential_columns and "purpose" not in credential_columns:
        connection.exec_driver_sql(
            "ALTER TABLE security_target_credentials "
            "ADD COLUMN purpose VARCHAR(64) NOT NULL DEFAULT 'agent_runtime'"
        )
        connection.exec_driver_sql(
            "UPDATE security_target_credentials SET purpose = 'dify_app_api' "
            "WHERE target_id IN (SELECT target_id FROM security_targets WHERE connector_type = 'dify')"
        )
    if credential_columns:
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_security_target_credentials_purpose "
            "ON security_target_credentials (purpose)"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_security_target_credential_purpose_version "
            "ON security_target_credentials (target_id, purpose, version)"
        )

    finding_columns = {
        row[1] for row in connection.exec_driver_sql("PRAGMA table_info(security_findings)").fetchall()
    }
    if finding_columns and "asset_id" not in finding_columns:
        connection.exec_driver_sql("ALTER TABLE security_findings ADD COLUMN asset_id VARCHAR(512)")
    if finding_columns:
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_security_findings_asset_id ON security_findings (asset_id)"
        )

    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS backend_schema_migrations "
        "(name VARCHAR(128) PRIMARY KEY, applied_at DATETIME NOT NULL)"
    )
    connection.exec_driver_sql(
        "INSERT OR IGNORE INTO backend_schema_migrations (name, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
        (MIGRATION_NAME,),
    )
