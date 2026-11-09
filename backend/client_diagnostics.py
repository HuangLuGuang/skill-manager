"""Client operational logs, separate from Agent execution evidence."""
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint, text, func, case, literal_column
from sqlalchemy.schema import CreateIndex

from .sqlite_db import Base, SessionLocal
from .services.retention import delete_batch

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
RETENTION_DAYS = 7
MAX_CLIENT_RECORDS = 10_000
MAX_CONTENT_BYTES = 1024 ** 3


class DiagnosticSettings(Base):
    __tablename__ = "client_diagnostic_settings"
    scope = Column(String, primary_key=True)
    level = Column(String, nullable=False, default="ERROR")


class DiagnosticDebugLease(Base):
    __tablename__ = "client_diagnostic_debug_leases"
    scope = Column(String, primary_key=True)
    expires_at = Column(DateTime, nullable=False)


class DiagnosticUsage(Base):
    __tablename__ = "client_diagnostic_usage"
    scope = Column(String, primary_key=True)
    records = Column(Integer, nullable=False, default=0)
    bytes = Column(Integer, nullable=False, default=0)


class DiagnosticLog(Base):
    __tablename__ = "client_diagnostic_logs"
    id = Column(Integer, primary_key=True)
    client_id = Column(String, nullable=False)
    record_id = Column(String, nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    level = Column(String, nullable=False)
    module = Column(String, nullable=False)
    event = Column(String, nullable=False)
    version = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("client_id", "record_id"),
        Index("ix_client_diagnostics_time", "client_id", "occurred_at", "id"),
        Index("ix_client_diagnostics_retention", "received_at"),
        Index("ix_client_diagnostics_client_retention", "client_id", "received_at", "id"),
    )


Index("ix_client_diagnostics_incident", DiagnosticLog.client_id,
      func.json_extract(DiagnosticLog.content, literal_column("'$.fields.incident_id'")),
      DiagnosticLog.occurred_at, DiagnosticLog.event, DiagnosticLog.level, DiagnosticLog.module)


def ensure_indexes(engine):
    # SQLite expression indexes are omitted by SQLAlchemy's checkfirst reflection.
    with engine.begin() as connection:
        for index in DiagnosticLog.__table__.indexes:
            connection.execute(CreateIndex(index, if_not_exists=True))


def unresolved_incidents(db, client_ids):
    """Group retained incidents by occurrence time, including late uploads."""
    row = DiagnosticLog
    incident = func.json_extract(row.content, literal_column("'$.fields.incident_id'"))
    failed = func.max(case((row.event == 'sync_failed', row.occurred_at)))
    recovered = func.max(case((row.event == 'sync_recovered', row.occurred_at)))
    now = datetime.utcnow()
    return db.query(row.client_id.label('client_id'), incident.label('incident_id'),
                    failed.label('failed_at')).filter(
        row.client_id.in_(client_ids), row.event.in_(['sync_failed', 'sync_recovered']),
        row.occurred_at >= now - timedelta(days=RETENTION_DAYS), row.occurred_at <= now,
        func.length(incident) == 32,
        ((row.event == 'sync_failed') & (row.level == 'ERROR')) |
        ((row.event == 'sync_recovered') & (row.level == 'INFO')),
    ).group_by(row.client_id, incident).having(failed.is_not(None), (recovered.is_(None)) | (failed > recovered))


def configuration(db, client_id=None):
    def effective(row, scope):
        level = row.level if row else "ERROR"
        lease = db.get(DiagnosticDebugLease, scope) if level in {"DEBUG", "INFO"} else None
        if lease and lease.expires_at <= datetime.utcnow():
            return "ERROR", None
        return level, lease.expires_at.isoformat() + "Z" if lease else None

    global_row = db.get(DiagnosticSettings, "global")
    global_level, global_expiry = effective(global_row, "global")
    row = db.get(DiagnosticSettings, "client:" + client_id) if client_id else global_row
    level, expiry = effective(row, "client:" + client_id if client_id else "global")
    if client_id and row is None:
        level = "INHERIT"
    return {"level": level, "effective_level": global_level if level == "INHERIT" else level,
            "expires_at": global_expiry if level == "INHERIT" else expiry}


def initialize_usage(db):
    # Bootstrap once; triggers account for inserts, retries and deletes in the same transaction.
    if db.execute(text("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='diagnostics_usage_insert'")).first():
        return
    db.execute(text("DELETE FROM client_diagnostic_usage"))
    db.execute(text("INSERT INTO client_diagnostic_usage SELECT 'global', count(*), coalesce(sum(length(CAST(content AS BLOB))),0) FROM client_diagnostic_logs"))
    db.execute(text("INSERT INTO client_diagnostic_usage SELECT 'client:' || client_id, count(*), sum(length(CAST(content AS BLOB))) FROM client_diagnostic_logs GROUP BY client_id"))
    for operation, sign, row in [("insert", "+", "NEW"), ("delete", "-", "OLD")]:
        statements = []
        for scope in ["'global'", f"'client:' || {row}.client_id"]:
            statements.append(f"INSERT OR IGNORE INTO client_diagnostic_usage VALUES ({scope},0,0);")
            statements.append(f"UPDATE client_diagnostic_usage SET records=records {sign} 1, bytes=bytes {sign} length(CAST({row}.content AS BLOB)) WHERE scope={scope};")
        db.execute(text(f"CREATE TRIGGER IF NOT EXISTS diagnostics_usage_{operation} AFTER {operation.upper()} ON client_diagnostic_logs BEGIN {' '.join(statements)} END"))


def trim_capacity(db):
    over = db.execute(text("SELECT scope,records FROM client_diagnostic_usage WHERE scope != 'global' AND records > :limit LIMIT 1"), {"limit": MAX_CLIENT_RECORDS}).first()
    if over:
        return delete_batch(db, DiagnosticLog, DiagnosticLog.client_id == over.scope.removeprefix("client:"),
                            limit=min(500, over.records - MAX_CLIENT_RECORDS), order_by=[DiagnosticLog.received_at, DiagnosticLog.id])
    size = db.execute(text("SELECT bytes FROM client_diagnostic_usage WHERE scope='global'")).scalar() or 0
    if size > MAX_CONTENT_BYTES:
        return delete_batch(db, DiagnosticLog, DiagnosticLog.id >= 0, order_by=[DiagnosticLog.received_at, DiagnosticLog.id])
    return 0


def cleanup_once():
    with SessionLocal() as db:
        initialize_usage(db)
        count = delete_batch(db, DiagnosticLog, DiagnosticLog.received_at < datetime.utcnow() - timedelta(days=RETENTION_DAYS))
        trimmed = trim_capacity(db) if count < 500 else 0
        db.commit()
        return count == 500 or bool(trimmed)
