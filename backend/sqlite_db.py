from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from fastapi import Request

from .config import settings


db_path = Path(settings.SQLITE_PATH)
db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


with engine.begin() as connection:
    connection.exec_driver_sql("PRAGMA journal_mode=WAL")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db(request: Request):
    db = SessionLocal()
    try:
        path = request.url.path
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (
            path.startswith(("/api/v1/iam/users", "/api/v1/iam/roles", "/api/v1/iam/menus", "/api/v1/users"))
            or path == "/api/auth/register"
        ):
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield db
    finally:
        db.close()
