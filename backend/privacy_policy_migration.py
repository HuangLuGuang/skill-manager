"""Preserve legacy policy selection while adding credential assignments."""


def migrate_privacy_policy_selection(engine):
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(access_tokens)")}
        if "privacy_policy_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE access_tokens ADD COLUMN privacy_policy_id INTEGER REFERENCES privacy_policies(id)")
        conn.exec_driver_sql(
            "INSERT OR IGNORE INTO system_configs (key, value) "
            "SELECT 'privacy.default_policy_id', CAST(id AS TEXT) FROM privacy_policies "
            "WHERE group_id IS NULL ORDER BY id LIMIT 1"
        )
