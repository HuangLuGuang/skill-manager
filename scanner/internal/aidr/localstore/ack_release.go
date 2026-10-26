package localstore

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
)

// Release only durable platform-confirmed payloads. Identity hashes and source
// observation metadata remain available for deduplication and retirement.
func releaseAcknowledgedPayloads(tx *sql.Tx, indexed bool) error {
	logicalIndex, coverageIndex := "", ""
	if indexed {
		logicalIndex = " INDEXED BY logical_events_release"
		coverageIndex = " INDEXED BY coverage_release"
	}
	// Retention indexes include released history; pin cleanup to retained bodies.
	for _, statement := range []string{
		`UPDATE logical_events` + logicalIndex + ` SET source_id=coalesce(source_id,json_extract(payload,'$.source_id')), observed_at=coalesce(observed_at,json_extract(payload,'$.observed_at')), payload=NULL WHERE acked_ns IS NOT NULL AND payload IS NOT NULL`,
		`UPDATE evidence SET payload=NULL WHERE payload IS NOT NULL AND EXISTS (SELECT 1 FROM logical_events WHERE id=evidence.logical_id AND acked_ns IS NOT NULL)`,
		`UPDATE coverage_history` + coverageIndex + ` SET payload='',payload_encoding='released' WHERE acked_ns IS NOT NULL AND payload_encoding!='released'`,
	} {
		if _, err := tx.Exec(statement); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) initializeACKRelease(ctx context.Context) error {
	rows, err := s.db.QueryContext(ctx, `PRAGMA table_info(logical_events)`)
	if err != nil {
		return err
	}
	columns := map[string]bool{}
	for rows.Next() {
		var cid, notnull, pk int
		var name, kind string
		var defaultValue any
		if err = rows.Scan(&cid, &name, &kind, &notnull, &defaultValue, &pk); err != nil {
			rows.Close()
			return err
		}
		columns[name] = true
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, column := range []string{"source_id", "observed_at"} {
		if !columns[column] {
			if _, err = tx.Exec(`ALTER TABLE logical_events ADD COLUMN ` + column + ` TEXT`); err != nil {
				return err
			}
		}
	}
	// Legacy ACK bodies must release space before optional indexes allocate pages.
	if err = releaseAcknowledgedPayloads(tx, false); err != nil {
		return err
	}
	if err = tx.Commit(); err != nil {
		return err
	}
	var migrated int
	if err = s.db.QueryRowContext(ctx, `SELECT count(*) FROM metadata WHERE key='ack_payload_release_version' AND value='1'`).Scan(&migrated); err != nil {
		return err
	}
	if migrated == 0 {
		var confirmed int
		if err = s.db.QueryRowContext(ctx, `SELECT count(*) FROM logical_events WHERE acked_ns IS NOT NULL`).Scan(&confirmed); err != nil {
			return err
		}
		if confirmed > 0 {
			// Clearing large legacy bodies leaves partially occupied B-tree pages.
			// Incremental vacuum only frees whole pages; repack once on upgrade.
			if _, err = s.db.ExecContext(ctx, `VACUUM`); err != nil {
				return err
			}
		}
		if _, err = s.db.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('ack_payload_release_version','1') ON CONFLICT(key) DO UPDATE SET value='1'`); err != nil {
			return err
		}
	}
	return s.reclaimPages(ctx, 0)
}

func (s *Store) initializeMaintenanceIndexes(ctx context.Context) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, statement := range []string{
		`CREATE INDEX IF NOT EXISTS sources_revision ON sources(revision)`,
		`CREATE INDEX IF NOT EXISTS sources_discovery ON sources(id,CAST(json_extract(cursor,'$.offset') AS INTEGER)) WHERE json_extract(cursor,'$.context_repair') IS NULL`,
		`CREATE INDEX IF NOT EXISTS logical_events_release ON logical_events(acked_ns) WHERE payload IS NOT NULL`,
		`CREATE INDEX IF NOT EXISTS evidence_release ON evidence(logical_id) WHERE payload IS NOT NULL`,
		`CREATE INDEX IF NOT EXISTS coverage_release ON coverage_history(acked_ns) WHERE payload_encoding!='released'`,
		`CREATE INDEX IF NOT EXISTS logical_events_retention ON logical_events(acked_ns) WHERE acked_ns IS NOT NULL`,
		`CREATE INDEX IF NOT EXISTS logical_events_retention_source ON logical_events(CAST(coalesce(source_id,json_extract(payload,'$.source_id')) AS TEXT))`,
		`CREATE INDEX IF NOT EXISTS coverage_source ON coverage_history(source_id)`,
		`CREATE INDEX IF NOT EXISTS coverage_retention ON coverage_history(acked_ns) WHERE acked_ns IS NOT NULL`,
	} {
		if _, err = tx.ExecContext(ctx, statement); err != nil {
			// A full queue must remain open for ACK/draining without optional indexes.
			if errors.Is(storageError(err), ErrCapacity) {
				return nil
			}
			return err
		}
	}
	if err = tx.Commit(); err != nil {
		if errors.Is(storageError(err), ErrCapacity) {
			return nil
		}
		return err
	}
	s.maintenanceIndexed = true
	return nil
}

func (s *Store) reclaimPages(ctx context.Context, pages int) error {
	statement := `PRAGMA incremental_vacuum`
	if pages > 0 {
		statement = fmt.Sprintf(`PRAGMA incremental_vacuum(%d)`, pages)
	}
	rows, err := s.db.QueryContext(ctx, statement)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
	}
	return rows.Err()
}
