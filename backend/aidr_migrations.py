"""Transactional SQLite upgrade preserving P1 evidence and receipt identities."""
from sqlalchemy import MetaData
from sqlalchemy.schema import CreateIndex, CreateTable


def upgrade_aidr_schema(engine):
    from .aidr_models import AidrDevice, AidrBatch, AidrEvent, AidrSource, AidrCoverageRecord, AidrLegacyDestination

    tables = [m.__table__ for m in (AidrDevice, AidrBatch, AidrEvent, AidrSource, AidrCoverageRecord)]
    if engine.dialect.name != "sqlite":
        raise RuntimeError("aidr_migration_backend_unsupported")
    with engine.connect() as conn:
        foreign_keys = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        try:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            risk_columns = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("aidr_risk_findings")')}
            if risk_columns and 'control_code' not in risk_columns:
                conn.exec_driver_sql("ALTER TABLE aidr_risk_findings ADD COLUMN control_code VARCHAR(128) NOT NULL DEFAULT ''")
            if risk_columns and 'disposition' not in risk_columns:
                conn.exec_driver_sql("ALTER TABLE aidr_risk_findings ADD COLUMN disposition VARCHAR(32) NOT NULL DEFAULT 'open'")
            if risk_columns and 'disposition_revision' not in risk_columns:
                conn.exec_driver_sql("ALTER TABLE aidr_risk_findings ADD COLUMN disposition_revision INTEGER NOT NULL DEFAULT 0")
            # Rebuild only derived overview metadata; original evidence and ACKs stay intact.
            rebuild_overview = False
            for name in ('aidr_overview_evidence', 'aidr_overview_operations'):
                columns = {r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{name}")')}
                if columns and 'command_counts_json' not in columns:
                    conn.exec_driver_sql(f"ALTER TABLE {name} ADD COLUMN command_counts_json TEXT NOT NULL DEFAULT '{{}}'")
                    rebuild_overview = True
            if rebuild_overview:
                for name in ('aidr_overview_evidence', 'aidr_overview_operations', 'aidr_overview_buckets',
                             'aidr_overview_command_buckets', 'aidr_overview_watermarks'):
                    if conn.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).first():
                        conn.exec_driver_sql(f'DELETE FROM {name}')
            runtime_columns = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("client_runtime_governance")')}
            if runtime_columns and "supports_tasks" not in runtime_columns:
                conn.exec_driver_sql("ALTER TABLE client_runtime_governance ADD COLUMN supports_tasks BOOLEAN NOT NULL DEFAULT 0")
                # Only a valid stored task protocol establishes this capability.
                # Preserve the original report and its observation time.
                from .runtime_governance import Report
                from pydantic import ValidationError
                for client_id, raw in conn.exec_driver_sql("SELECT client_id,report_json FROM client_runtime_governance"):
                    try:
                        report = Report.model_validate_json(raw)
                    except ValidationError:
                        continue
                    if report.protocol in (1, 2, 3, 4):
                        conn.exec_driver_sql("UPDATE client_runtime_governance SET supports_tasks=1 WHERE client_id=?", (client_id,))
            governance_columns = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("client_governance_policies")')}
            receipt_columns = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("aidr_policy_receipts")')}
            if receipt_columns and 'capture_json' not in receipt_columns:
                conn.exec_driver_sql('ALTER TABLE aidr_policy_receipts ADD COLUMN capture_json TEXT')
            if receipt_columns and 'lifecycle_json' not in receipt_columns:
                conn.exec_driver_sql('ALTER TABLE aidr_policy_receipts ADD COLUMN lifecycle_json TEXT')
            if receipt_columns and 'skill_audit_json' not in receipt_columns:
                conn.exec_driver_sql('ALTER TABLE aidr_policy_receipts ADD COLUMN skill_audit_json TEXT')
            skill_columns = {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("aidr_skill_uses")')}
            if skill_columns:
                if 'next_check_at' not in skill_columns:
                    conn.exec_driver_sql("ALTER TABLE aidr_skill_uses ADD COLUMN next_check_at DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'")
                conn.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_aidr_skill_due ON aidr_skill_uses(expired_at,next_check_at,id)')
            for name in ('aidr_events', 'aidr_hook_events', 'aidr_coverage_records', 'aidr_operations', 'aidr_runtime_records'):
                columns = {r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{name}")')}
                if not columns:
                    continue
                if 'expired_at' not in columns:
                    conn.exec_driver_sql(f'ALTER TABLE "{name}" ADD COLUMN expired_at DATETIME')
                if name == 'aidr_operations' and 'received_at' not in columns:
                    # Existing derived views receive a full retention window at
                    # upgrade; no historic event, cursor or batch is rewritten.
                    conn.exec_driver_sql('ALTER TABLE aidr_operations ADD COLUMN received_at DATETIME')
                    conn.exec_driver_sql('UPDATE aidr_operations SET received_at=CURRENT_TIMESTAMP WHERE received_at IS NULL')
                if name == 'aidr_runtime_records' and 'content_hash' not in columns:
                    conn.exec_driver_sql('ALTER TABLE aidr_runtime_records ADD COLUMN content_hash VARCHAR(64)')
                conn.exec_driver_sql(f'CREATE INDEX IF NOT EXISTS ix_{name}_retention ON "{name}"(expired_at,received_at)')
            if governance_columns and "runtime_governance_json" not in governance_columns:
                conn.exec_driver_sql("ALTER TABLE client_governance_policies ADD COLUMN runtime_governance_json TEXT NOT NULL DEFAULT 'null'")
            AidrLegacyDestination.__table__.create(conn, checkfirst=True)
            for table in tables:
                columns = {r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
                if "group_id" not in columns:
                    continue
                if table.name == "aidr_devices":
                    conn.exec_driver_sql("INSERT OR IGNORE INTO aidr_legacy_destinations(client_id,suffix) SELECT client_id,CAST(group_id AS TEXT) FROM aidr_devices")
                metadata = MetaData()
                for existing in table.metadata.sorted_tables:
                    existing.to_metadata(metadata)
                replacement = table.to_metadata(metadata, name=table.name + "_upgrade")
                conn.execute(CreateTable(replacement))
                names = ", ".join('"' + c + '"' for c in table.columns.keys())
                conn.exec_driver_sql(f'INSERT INTO "{replacement.name}" ({names}) SELECT {names} FROM "{table.name}"')
                conn.exec_driver_sql(f'DROP TABLE "{table.name}"')
                conn.exec_driver_sql(f'ALTER TABLE "{replacement.name}" RENAME TO "{table.name}"')
                for index in table.indexes:
                    index.create(conn)
            for table in tables:
                if conn.exec_driver_sql(f'PRAGMA foreign_key_check("{table.name}")').first():
                    raise RuntimeError("aidr_migration_reference_invalid")
            from .aidr_operations import backfill_operations, repair_codex_session_projections
            backfill_operations(conn)
            repair_codex_session_projections(conn)
            from .aidr_correlation import install_indexes
            install_indexes(conn)
            from .aidr_models import SESSION_MESSAGE_INDEX, SESSION_LIST_INDEXES, RUNTIME_GOVERNANCE_INDEXES, HOOK_RELATED_INDEX, SKILL_EVIDENCE_INDEXES
            SESSION_MESSAGE_INDEX.create(conn, checkfirst=True)
            for index in (*SESSION_LIST_INDEXES, *RUNTIME_GOVERNANCE_INDEXES, HOOK_RELATED_INDEX, *SKILL_EVIDENCE_INDEXES):
                # SQLite expression indexes are not reflected by SQLAlchemy.
                conn.execute(CreateIndex(index, if_not_exists=True))
            from .aidr_enforcement import RUNTIME_QUERY_INDEXES
            if conn.exec_driver_sql('PRAGMA table_info("aidr_runtime_records")').first():
                for index in RUNTIME_QUERY_INDEXES:
                    conn.execute(CreateIndex(index, if_not_exists=True))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")
            conn.commit()
