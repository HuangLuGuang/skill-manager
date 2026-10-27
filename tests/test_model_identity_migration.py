import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from backend import migrate_compression


def test_model_identity_migration_preserves_names_and_is_idempotent(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE model_endpoints (id INTEGER PRIMARY KEY, provider_id INTEGER, name VARCHAR(128) UNIQUE)")
        conn.exec_driver_sql("INSERT INTO model_endpoints VALUES (1, 1, 'glm-original')")
        for table in ("llm_api_keys", "model_providers", "llm_usage_metrics", "llm_request_audit"):
            conn.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
    monkeypatch.setattr(migrate_compression, "engine", engine)
    migrate_compression.migrate()
    migrate_compression.migrate()
    with engine.begin() as conn:
        assert conn.exec_driver_sql("SELECT guard_adapter FROM model_endpoints").scalar_one() == "generic"
        assert conn.exec_driver_sql("SELECT name, upstream_name FROM model_endpoints").one() == ("glm-original", "glm-original")
        conn.exec_driver_sql("INSERT INTO model_endpoints (id, provider_id, name, upstream_name) VALUES (2, 2, 'other/glm-original', 'glm-original')")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO model_endpoints (id, provider_id, name, upstream_name) VALUES (3, 2, 'duplicate', 'glm-original')")


def test_model_provider_migration_removes_legacy_required_compression_column(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-provider.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE model_providers (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                base_url VARCHAR(512) NOT NULL,
                api_format VARCHAR(32) NOT NULL DEFAULT 'openai',
                api_key TEXT,
                enabled BOOLEAN NOT NULL,
                timeout_seconds INTEGER NOT NULL,
                enable_compression BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO model_providers
                (id, name, base_url, api_format, enabled, timeout_seconds, enable_compression, created_at, updated_at)
            VALUES (1, 'legacy', 'https://legacy.example', 'openai', 1, 60, 1, '2026-01-01', '2026-01-01')
        """)
        for table in ("llm_api_keys", "llm_usage_metrics", "llm_request_audit"):
            conn.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
    monkeypatch.setattr(migrate_compression, "engine", engine)

    migrate_compression.migrate()
    migrate_compression.migrate()

    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(model_providers)")}
        assert "enable_compression" not in columns
        assert conn.exec_driver_sql("SELECT name FROM model_providers").scalar_one() == "legacy"
        assert conn.exec_driver_sql("SELECT auth_type, custom_headers_encrypted FROM model_providers").one() == ("bearer", None)
        conn.exec_driver_sql("UPDATE model_providers SET auth_type = 'raw', custom_headers_encrypted = 'encrypted-test'")
        conn.exec_driver_sql("ALTER TABLE model_providers ADD COLUMN enable_compression BOOLEAN NOT NULL DEFAULT 1")
    migrate_compression.migrate()
    migrate_compression.migrate()
    with engine.begin() as conn:
        assert conn.exec_driver_sql("SELECT auth_type, custom_headers_encrypted FROM model_providers").one() == ("raw", "encrypted-test")
        conn.exec_driver_sql("""
            INSERT INTO model_providers
                (id, name, base_url, api_format, enabled, timeout_seconds, created_at, updated_at)
            VALUES (2, 'current', 'https://current.example', 'openai', 1, 60, '2026-01-02', '2026-01-02')
        """)
