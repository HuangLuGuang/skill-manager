from __future__ import annotations

from sqlalchemy import create_engine, inspect

from backend.security_target_migration import (
    MIGRATION_NAME,
    migrate_security_target_classification,
)


def test_historical_security_targets_are_classified_without_deleting_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'historical.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE security_targets ("
            "id INTEGER PRIMARY KEY, target_id VARCHAR(64) NOT NULL, "
            "name VARCHAR(128) NOT NULL, target_type VARCHAR(64) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO security_targets (target_id, name, target_type) VALUES "
            "('ast_mcp', 'Old MCP', 'mcp_gateway'), "
            "('ast_dify', 'Old Dify', 'dify'), "
            "('ast_coze', 'Old Coze', 'coze-com'), "
            "('ast_http', 'Old HTTP', 'http'), "
            "('ast_ws', 'Old WebSocket', 'websocket'), "
            "('ast_openai', 'Old OpenAI', 'openai')"
        )

        migrate_security_target_classification(connection)
        migrate_security_target_classification(connection)

        rows = connection.exec_driver_sql(
            "SELECT target_id, asset_type, connector_type FROM security_targets ORDER BY target_id"
        ).fetchall()
        migrations = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM backend_schema_migrations WHERE name = ?",
            (MIGRATION_NAME,),
        ).scalar_one()

    assert rows == [
        ("ast_coze", "agent", "coze"),
        ("ast_dify", "agent", "dify"),
        ("ast_http", "agent", "custom_http"),
        ("ast_mcp", "mcp", "mcp_gateway"),
        ("ast_openai", "agent", "openai_compatible"),
        ("ast_ws", "agent", "websocket"),
    ]
    assert migrations == 1
    assert {index["name"] for index in inspect(engine).get_indexes("security_targets")} >= {
        "ix_security_targets_asset_type",
        "ix_security_targets_connector_type",
    }
    engine.dispose()
