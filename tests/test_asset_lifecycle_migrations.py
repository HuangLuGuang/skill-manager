from sqlalchemy import create_engine, inspect

from backend import models
from backend.asset_lifecycle_migrations import upgrade_asset_lifecycle_schema
from backend.sqlite_db import Base


def test_upgrade_preserves_history_and_is_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP TABLE asset_sources')
        conn.exec_driver_sql('CREATE TABLE asset_sources (source_id TEXT PRIMARY KEY, template_target_id TEXT)')
        conn.exec_driver_sql('DROP INDEX ix_asset_lifecycle_events_next_attempt_at')
        for table, column in [
            ('asset_sync_runs', 'updated_at'),
            ('security_agent_assets', 'display_name'),
            ('agent_risk_issues', 'reviewed_config_fingerprint'),
            ('asset_lifecycle_events', 'error_code'),
            ('asset_lifecycle_events', 'next_attempt_at'),
        ]:
            conn.exec_driver_sql(f'ALTER TABLE {table} DROP COLUMN {column}')
        conn.exec_driver_sql('DROP TABLE agent_risk_assessments')
        conn.exec_driver_sql('CREATE TABLE agent_risk_assessments (assessment_id TEXT PRIMARY KEY, '
                             'agent_id TEXT, input_hash TEXT, payload_json TEXT, created_at DATETIME, '
                             'UNIQUE(agent_id, input_hash))')
        conn.exec_driver_sql("INSERT INTO agent_risk_assessments VALUES ('one','agent','hash','{}','2026-09-08')")
    upgrade_asset_lifecycle_schema(engine)
    upgrade_asset_lifecycle_schema(engine)
    assert 'display_name' in {c['name'] for c in inspect(engine).get_columns('security_agent_assets')}
    assert 'connection_hash' in {c['name'] for c in inspect(engine).get_columns('asset_sources')}
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO agent_risk_assessments VALUES ('two','agent','hash','{}','2026-09-09')")
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM agent_risk_assessments').scalar() == 2
    assert models.AgentRiskAssessment.__tablename__ == 'agent_risk_assessments'
