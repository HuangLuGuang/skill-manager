"""为已有数据库添加 Headroom 压缩相关列。

SQLite 不支持 ALTER TABLE ADD COLUMN IF NOT EXISTS，
此脚本检查 PRAGMA table_info 后按需添加列。
"""

from backend.sqlite_db import engine


def _rebuild_model_providers_without_legacy_compression(conn) -> None:
    """Remove a historic provider-only compression column.

    ``enable_compression`` belongs to issued API credentials, not upstream
    providers.  Some historical schemas contain it on ``model_providers`` as
    NOT NULL without a server default.  Current provider
    creation code does not (and should not) populate that unrelated column.
    SQLite cannot drop a column compatibly across the versions we support, so
    preserve the provider records while rebuilding the table's current shape.
    """
    conn.exec_driver_sql(
        """
        CREATE TABLE model_providers__pre_compression_repair (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            base_url VARCHAR(512) NOT NULL,
            api_format VARCHAR(32) NOT NULL DEFAULT 'openai',
            api_key TEXT,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            timeout_seconds INTEGER NOT NULL DEFAULT 60,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO model_providers__pre_compression_repair
            (id, name, base_url, api_format, api_key, enabled, timeout_seconds, created_at, updated_at)
        SELECT id, name, base_url, api_format, api_key, enabled, timeout_seconds, created_at, updated_at
        FROM model_providers
        """
    )
    conn.exec_driver_sql("DROP TABLE model_providers")
    conn.exec_driver_sql(
        "ALTER TABLE model_providers__pre_compression_repair RENAME TO model_providers"
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_model_providers_name ON model_providers (name)"
    )


def migrate() -> None:
    with engine.begin() as conn:
        dialect = conn.engine.dialect.name
        if dialect != "sqlite":
            return

        existing_models = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(model_endpoints)")}
        if existing_models:
            if "upstream_name" not in existing_models:
                conn.exec_driver_sql("ALTER TABLE model_endpoints ADD COLUMN upstream_name VARCHAR(128)")
            conn.exec_driver_sql("UPDATE model_endpoints SET upstream_name = name WHERE upstream_name IS NULL")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_model_provider_upstream ON model_endpoints(provider_id, coalesce(upstream_name, name))")

        # llm_api_keys 表
        existing = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(llm_api_keys)"
            ).fetchall()
        }
        for col_name, col_type in [
            ("enable_compression", "BOOLEAN NOT NULL DEFAULT 0"),
            ("compression_level", "VARCHAR(32) NOT NULL DEFAULT 'auto'"),
        ]:
            if col_name not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE llm_api_keys ADD COLUMN {col_name} {col_type}"
                )

        # model_providers 表
        existing = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(model_providers)"
            ).fetchall()
        }
        if "api_format" not in existing:
            conn.exec_driver_sql(
                "ALTER TABLE model_providers ADD COLUMN api_format VARCHAR(32) NOT NULL DEFAULT 'openai'"
            )
            existing.add("api_format")
        if "enable_compression" in existing:
            _rebuild_model_providers_without_legacy_compression(conn)

        # llm_usage_metrics 表
        existing = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(llm_usage_metrics)"
            ).fetchall()
        }
        for col_name, col_type in [
            ("pre_compression_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("post_compression_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("tokens_saved", "INTEGER NOT NULL DEFAULT 0"),
            ("compression_ratio", "FLOAT NOT NULL DEFAULT 0.0"),
            ("compression_duration_ms", "FLOAT NOT NULL DEFAULT 0.0"),
        ]:
            if col_name not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE llm_usage_metrics ADD COLUMN {col_name} {col_type}"
                )

        # llm_request_audit 表
        existing = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(llm_request_audit)"
            ).fetchall()
        }
        for col_name, col_type in [
            ("compression_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("compression_level", "VARCHAR(32)"),
            ("request_duration_ms", "FLOAT NOT NULL DEFAULT 0.0"),
            ("upstream_duration_ms", "FLOAT NOT NULL DEFAULT 0.0"),
            ("platform_duration_ms", "FLOAT NOT NULL DEFAULT 0.0"),
        ]:
            if col_name not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE llm_request_audit ADD COLUMN {col_name} {col_type}"
                )


if __name__ == "__main__":
    migrate()
    print("Compression migration completed.")
