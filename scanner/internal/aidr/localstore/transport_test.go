package localstore

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
)

func TestLegacyDestinationMigration(t *testing.T) {
	for _, target := range []string{"https://platform\ndevice", "https://other\ndevice", "https://platform\nother"} {
		t.Run(target, func(t *testing.T) {
			root, err := filepath.EvalSymlinks(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			s, err := Open(filepath.Join(root, "state"), DefaultLimits())
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			ctx := context.Background()
			old := "https://platform\ndevice\n17"
			_, err = s.db.Exec(`INSERT INTO metadata(key,value) VALUES('destination',?)`, hash([]byte(old)))
			if err != nil {
				t.Fatal(err)
			}
			stream, _ := s.StreamID(ctx)
			if err = s.BindDestination(ctx, target); !errors.Is(err, ErrLegacyDestination) {
				t.Fatal(err)
			}
			err = s.BindDestinationWithLegacy(ctx, target, target+"\n17")
			if target != "https://platform\ndevice" {
				if err == nil {
					t.Fatal("legacy queue rebound to another destination")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if err = s.BindDestination(ctx, target); err != nil {
				t.Fatal(err)
			}
			after, _ := s.StreamID(ctx)
			if after != stream {
				t.Fatal("stream changed")
			}
			if err = s.BindDestination(ctx, target+"other"); err == nil {
				t.Fatal("new binding lost")
			}
		})
	}
}

func TestLegacyMigrationPreservesFrozenBatchAndCursor(t *testing.T) {
	ctx := context.Background()
	dir := tempDir(t)
	s := openStore(t, dir, DefaultLimits())
	src := source(t, lines(3))
	collect(t, s, src)
	before, err := s.Prepare(ctx, 500, 1<<20)
	if err != nil || before == nil {
		t.Fatal(err)
	}
	var cursor string
	if err = s.db.QueryRow(`SELECT cursor FROM sources`).Scan(&cursor); err != nil {
		t.Fatal(err)
	}
	_, err = s.db.Exec(`INSERT INTO metadata(key,value) VALUES('destination',?)`, hash([]byte("https://platform\ndevice\n17")))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.BindDestinationWithLegacy(ctx, "https://platform\ndevice", "https://platform\ndevice\n17"); err != nil {
		t.Fatal(err)
	}
	s.Close()
	s = openStore(t, dir, DefaultLimits())
	after, err := s.Prepare(ctx, 500, 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	if before.ID != after.ID || before.Digest != after.Digest || string(before.Payload) != string(after.Payload) {
		t.Fatal("frozen batch changed")
	}
	var next string
	if err = s.db.QueryRow(`SELECT cursor FROM sources`).Scan(&next); err != nil || next != cursor {
		t.Fatal("cursor changed", err)
	}
	if err = s.Acknowledge(ctx, after.ID, "wrong"); err == nil {
		t.Fatal("invalid ACK accepted")
	}
	if status(t, s).Queued == 0 {
		t.Fatal("invalid ACK cleared queue")
	}
	if err = s.Acknowledge(ctx, after.ID, after.Digest); err != nil {
		t.Fatal(err)
	}
	if status(t, s).Queued != 0 {
		t.Fatal("valid ACK left queued data")
	}
}
