"""Transactional SQLite upgrade preserving P1 evidence and receipt identities."""
from sqlalchemy import MetaData
from sqlalchemy.schema import CreateTable


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
            from .aidr_operations import backfill_operations
            backfill_operations(conn)
            from .aidr_correlation import install_indexes
            install_indexes(conn)
            from .aidr_models import SESSION_MESSAGE_INDEX
            SESSION_MESSAGE_INDEX.create(conn, checkfirst=True)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")
            conn.commit()
