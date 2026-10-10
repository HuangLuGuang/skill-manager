package localstore

import (
	"bytes"
	"compress/gzip"
	"context"
)

// Coverage history is a local archive, independent of the immutable JSON outbox.
// Compress it losslessly; source checkpoints retain the full parser state.
func encodeCoverage(raw []byte) (any, string, error) {
	if len(raw) < 1024 {
		return string(raw), "json", nil
	}
	var buf bytes.Buffer
	w, err := gzip.NewWriterLevel(&buf, gzip.BestSpeed)
	if err != nil {
		return nil, "", err
	}
	if _, err = w.Write(raw); err != nil {
		return nil, "", err
	}
	if err = w.Close(); err != nil {
		return nil, "", err
	}
	if buf.Len() >= len(raw) {
		return string(raw), "json", nil
	}
	return buf.Bytes(), "gzip", nil
}

// Additive migration: older clients ignore this column and continue to use the
// JSON outbox. Only already-acknowledged legacy snapshots are rewritten.
func (s *Store) compactCoverageHistory(ctx context.Context) error {
	rows, err := s.db.QueryContext(ctx, `PRAGMA table_info(coverage_history)`)
	if err != nil {
		return err
	}
	found := false
	for rows.Next() {
		var cid, notnull, pk int
		var name, kind string
		var defaultValue any
		if err = rows.Scan(&cid, &name, &kind, &notnull, &defaultValue, &pk); err != nil {
			rows.Close()
			return err
		}
		found = found || name == "payload_encoding"
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	if !found {
		if _, err = s.db.ExecContext(ctx, `ALTER TABLE coverage_history ADD COLUMN payload_encoding TEXT NOT NULL DEFAULT 'json'`); err != nil {
			return err
		}
	}
	var after string
	changed := false
	for {
		rows, err = s.db.QueryContext(ctx, `SELECT id,payload FROM coverage_history WHERE id>? AND acked_ns IS NOT NULL AND payload_encoding='json' AND length(payload)>=1024 ORDER BY id LIMIT 128`, after)
		if err != nil {
			return err
		}
		type record struct {
			id  string
			raw []byte
		}
		var batch []record
		for rows.Next() {
			var r record
			if err = rows.Scan(&r.id, &r.raw); err != nil {
				rows.Close()
				return err
			}
			batch = append(batch, r)
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return err
		}
		if len(batch) == 0 {
			break
		}
		tx, err := s.db.BeginTx(ctx, nil)
		if err != nil {
			return err
		}
		for _, r := range batch {
			var stored any
			var encoding string
			stored, encoding, err = encodeCoverage(r.raw)
			if err == nil && encoding == "gzip" {
				_, err = tx.ExecContext(ctx, `UPDATE coverage_history SET payload=?,payload_encoding=? WHERE id=?`, stored, encoding, r.id)
				changed = true
			}
			if err != nil {
				break
			}
		}
		if err != nil {
			tx.Rollback()
			return err
		}
		if err = tx.Commit(); err != nil {
			return err
		}
		after = batch[len(batch)-1].id
	}
	if changed {
		// Consume every row: SQLite releases pages incrementally as this statement steps.
		rows, err = s.db.QueryContext(ctx, `PRAGMA incremental_vacuum`)
		if err != nil {
			return err
		}
		for rows.Next() {
		}
		err = rows.Err()
		rows.Close()
	}
	return err
}
