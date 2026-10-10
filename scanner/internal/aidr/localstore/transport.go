package localstore

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"errors"
	"regexp"
)

// StreamID namespaces source revisions across explicit new state directories.
func (s *Store) StreamID(ctx context.Context) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var id string
	err := s.db.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='stream_id'`).Scan(&id)
	if err == nil {
		return id, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return "", err
	}
	var nonce [16]byte
	if _, err = rand.Read(nonce[:]); err != nil {
		return "", err
	}
	id = hex.EncodeToString(nonce[:])
	_, err = s.db.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('stream_id',?)`, id)
	return id, err
}

// BindDestination prevents a pending queue from being sent to a different
// platform/device after a configuration change. Tokens are excluded.
func (s *Store) BindDestination(ctx context.Context, identity string) error {
	return s.BindDestinationWithLegacy(ctx, identity, "")
}

var ErrLegacyDestination = errors.New("aidr_upload_destination_migration_required")

// BindDestinationWithLegacy upgrades only a verified historical destination.
// Frozen batches, stream IDs, and source cursors are untouched.
func (s *Store) BindDestinationWithLegacy(ctx context.Context, identity, legacyIdentity string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(identity) == 0 || len(identity) > 4096 {
		return ErrInvalid
	}
	wanted := hash([]byte(identity))
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	var prior, version string
	err = tx.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='destination'`).Scan(&prior)
	if err == nil {
		e := tx.QueryRowContext(ctx, `SELECT value FROM metadata WHERE key='destination_version'`).Scan(&version)
		if e != nil && !errors.Is(e, sql.ErrNoRows) {
			return e
		}
		if version == "" {
			if legacyIdentity == "" {
				return ErrLegacyDestination
			}
			if prior != hash([]byte(legacyIdentity)) {
				return errors.New("aidr_upload_destination_changed")
			}
		} else if version != "2" || prior != wanted {
			return errors.New("aidr_upload_destination_changed")
		} else {
			return nil
		}
	} else if !errors.Is(err, sql.ErrNoRows) {
		return err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('destination',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, wanted); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('destination_version','2') ON CONFLICT(key) DO UPDATE SET value=excluded.value`); err != nil {
		return err
	}
	return tx.Commit()
}

var uploadCode = regexp.MustCompile(`^aidr_upload_[a-z_]{1,64}$`)

func (s *Store) SetUploadCode(ctx context.Context, code string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if code != "" && !uploadCode.MatchString(code) {
		return ErrInvalid
	}
	_, err := s.db.ExecContext(ctx, `INSERT INTO metadata(key,value) VALUES('upload_code',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value`, code)
	return err
}
