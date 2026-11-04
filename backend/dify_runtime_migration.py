"""Detach runtime ownership from optional scan targets without changing identities."""
from sqlalchemy import inspect


def upgrade_dify_runtime_schema(engine):
    with engine.connect() as conn:
        foreign_keys = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        try:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            inspector = inspect(conn)
            if inspector.has_table("dify_runtime_bindings"):
                columns = {c["name"]: c for c in inspector.get_columns("dify_runtime_bindings")}
                if "owner_user_id" not in columns:
                    conn.exec_driver_sql("ALTER TABLE dify_runtime_bindings ADD COLUMN owner_user_id INTEGER")
                    conn.exec_driver_sql("ALTER TABLE dify_runtime_bindings ADD COLUMN owner_group_id INTEGER")
                    conn.exec_driver_sql("""UPDATE dify_runtime_bindings SET
                        owner_user_id=(SELECT owner_user_id FROM security_targets WHERE target_id=dify_runtime_bindings.target_id),
                        owner_group_id=(SELECT owner_group_id FROM security_targets WHERE target_id=dify_runtime_bindings.target_id)""")
                if not columns["target_id"]["nullable"]:
                    # Rebuild the parent in one transaction; child FKs retain its original name.
                    conn.exec_driver_sql("""CREATE TABLE dify_runtime_bindings_new (
                        binding_id VARCHAR(64) NOT NULL PRIMARY KEY, target_id VARCHAR(64) UNIQUE REFERENCES security_targets(target_id),
                        agent_id VARCHAR(128) NOT NULL UNIQUE REFERENCES managed_agents(agent_id),
                        instance_id VARCHAR(128) NOT NULL, workspace_id VARCHAR(128) NOT NULL, app_id VARCHAR(128) NOT NULL,
                        mode VARCHAR(16) NOT NULL, revision INTEGER NOT NULL, policy_json TEXT NOT NULL, updated_at DATETIME NOT NULL,
                        owner_user_id INTEGER, owner_group_id INTEGER, UNIQUE(instance_id,workspace_id,app_id))""")
                    names = "binding_id,target_id,agent_id,instance_id,workspace_id,app_id,mode,revision,policy_json,updated_at,owner_user_id,owner_group_id"
                    conn.exec_driver_sql(f"INSERT INTO dify_runtime_bindings_new ({names}) SELECT {names} FROM dify_runtime_bindings")
                    conn.exec_driver_sql("DROP TABLE dify_runtime_bindings")
                    conn.exec_driver_sql("ALTER TABLE dify_runtime_bindings_new RENAME TO dify_runtime_bindings")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")
            conn.commit()
