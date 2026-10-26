"""Preserve credential identities across hard deletion and SQLite upgrades."""
import re


def migrate_access_token_ids(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        foreign_keys = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        try:
            # Serialize startup workers and make the table replacement fully transactional.
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            ddl = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='access_tokens'"
            ).scalar()
            if not ddl or re.search(r"\bAUTOINCREMENT\b", ddl, re.I):
                conn.commit()
                return
            high_water = conn.exec_driver_sql("SELECT coalesce(max(id), 0) FROM access_tokens").scalar()
            references = {
                "access_tokens": ["issued_by_client_token_id"],
                "managed_agents": ["runtime_token_id", "source_token_id"],
                "runtime_tasks": ["token_id"],
                "mcp_call_audits": ["token_id"],
                "mcp_tool_approvals": ["token_id"],
                "security_mcp_scan_sessions": ["token_id"],
                "security_scan_tasks": ["source_token_id"],
                "external_api_requests": ["token_id"],
                "external_skill_scans": ["source_token_id"],
                # These tables also contain legacy model keys; a higher floor is harmless.
                "llm_request_audit": ["api_key_id"],
                "llm_usage_metrics": ["api_key_id"],
            }
            for table, candidates in references.items():
                columns = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table}")')}
                for column in candidates:
                    if column in columns:
                        value = conn.exec_driver_sql(
                            f'SELECT coalesce(max("{column}"), 0) FROM "{table}"'
                        ).scalar()
                        high_water = max(high_water, value)

            audit_columns = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info(security_audit_events)')}
            if {"resource_type", "resource_id"} <= audit_columns:
                prefix = "/api/v1/access/tokens/"
                audited_id = conn.exec_driver_sql(
                    "SELECT coalesce(max(CAST(substr(resource_id, ?) AS INTEGER)), 0) "
                    "FROM security_audit_events WHERE resource_type='http_route' AND resource_id GLOB ?",
                    (len(prefix) + 1, prefix + "[0-9]*"),
                ).scalar()
                high_water = max(high_water, audited_id)

            # Preserve the stored schema, including historical columns, constraints and defaults.
            rebuilt, count = re.subn(
                r'CREATE TABLE\s+(?:"access_tokens"|access_tokens)',
                'CREATE TABLE access_tokens__monotonic_ids', ddl, count=1, flags=re.I,
            )
            rebuilt, table_pk = re.subn(
                r',\s*PRIMARY KEY\s*\(\s*id\s*\)', '', rebuilt, count=1, flags=re.I,
            )
            if table_pk:
                rebuilt, primary_key = re.subn(
                    r'\bid INTEGER\b', 'id INTEGER PRIMARY KEY AUTOINCREMENT',
                    rebuilt, count=1, flags=re.I,
                )
            else:
                rebuilt, primary_key = re.subn(
                    r'(\bid INTEGER(?: NOT NULL)? PRIMARY KEY)\b', r'\1 AUTOINCREMENT',
                    rebuilt, count=1, flags=re.I,
                )
            if count != 1 or primary_key != 1:
                raise RuntimeError("Unsupported access_tokens primary key schema")
            objects = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE tbl_name='access_tokens' "
                "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
            ).scalars().all()
            conn.exec_driver_sql(rebuilt)
            conn.exec_driver_sql("INSERT INTO access_tokens__monotonic_ids SELECT * FROM access_tokens")
            conn.exec_driver_sql("DROP TABLE access_tokens")
            conn.exec_driver_sql("ALTER TABLE access_tokens__monotonic_ids RENAME TO access_tokens")
            for statement in objects:
                conn.exec_driver_sql(statement)
            conn.exec_driver_sql("DELETE FROM sqlite_sequence WHERE name='access_tokens'")
            conn.exec_driver_sql(
                "INSERT INTO sqlite_sequence(name, seq) VALUES ('access_tokens', ?)", (high_water,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")
            conn.commit()
