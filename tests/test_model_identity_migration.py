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
        assert conn.exec_driver_sql("SELECT name, upstream_name FROM model_endpoints").one() == ("glm-original", "glm-original")
        conn.exec_driver_sql("INSERT INTO model_endpoints VALUES (2, 2, 'other/glm-original', 'glm-original')")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO model_endpoints VALUES (3, 2, 'duplicate', 'glm-original')")
