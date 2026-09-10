"""Upgrade persisted asset lifecycle tables without discarding evidence."""

from types import SimpleNamespace

from sqlalchemy import MetaData
from sqlalchemy.schema import CreateTable


def upgrade_asset_lifecycle_schema(engine):
    from .asset_lifecycle_models import AgentRiskAssessment, AssetLifecycleEvent
    from .services.asset_sync import connection_hash

    if engine.dialect.name != "sqlite":
        return
    additions = {
        "asset_sources": {"connection_hash": "VARCHAR(64)"},
        "asset_sync_runs": {"updated_at": "DATETIME"},
        "security_agent_assets": {"display_name": "VARCHAR(512)"},
        "agent_risk_issues": {"reviewed_config_fingerprint": "VARCHAR(64)"},
        "asset_lifecycle_events": {"next_attempt_at": "DATETIME", "error_code": "VARCHAR(128)"},
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            existing = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        for index in AssetLifecycleEvent.__table__.indexes:
            index.create(conn, checkfirst=True)
        conn.exec_driver_sql("UPDATE asset_sync_runs SET updated_at = created_at WHERE updated_at IS NULL")
        rows = conn.exec_driver_sql(
            "SELECT s.source_id, t.* FROM asset_sources s JOIN security_targets t "
            "ON t.target_id = s.template_target_id WHERE s.connection_hash IS NULL"
        ).mappings().all()
        for row in rows:
            digest = connection_hash(SimpleNamespace(**row))
            conn.exec_driver_sql(
                "UPDATE asset_sources SET connection_hash = ? WHERE source_id = ?", (digest, row["source_id"])
            )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_source_connection ON asset_sources(connection_hash)"
        )
        unique_inputs = False
        for index in conn.exec_driver_sql("PRAGMA index_list(agent_risk_assessments)").all():
            if index[2]:
                names = [r[2] for r in conn.exec_driver_sql('PRAGMA index_info("' + index[1].replace('"', '""') + '")')]
                unique_inputs |= names == ["agent_id", "input_hash"]
        if unique_inputs:
            metadata = MetaData()
            for table in AgentRiskAssessment.metadata.sorted_tables:
                table.to_metadata(metadata)
            replacement = AgentRiskAssessment.__table__.to_metadata(metadata, name="agent_risk_assessments_upgrade")
            conn.execute(CreateTable(replacement))
            columns = ", ".join(AgentRiskAssessment.__table__.columns.keys())
            conn.exec_driver_sql(
                f"INSERT INTO agent_risk_assessments_upgrade ({columns}) SELECT {columns} FROM agent_risk_assessments"
            )
            conn.exec_driver_sql("DROP TABLE agent_risk_assessments")
            conn.exec_driver_sql("ALTER TABLE agent_risk_assessments_upgrade RENAME TO agent_risk_assessments")
            for index in AgentRiskAssessment.__table__.indexes:
                index.create(conn, checkfirst=True)
