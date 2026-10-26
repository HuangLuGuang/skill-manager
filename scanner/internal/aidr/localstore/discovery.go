package localstore

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/agentlog"
	"strings"
	"time"

	"github.com/fsnotify/fsnotify"
)

// The directory frontier and source catalogue are durable; file read cursors
// remain owned by Collect. An interrupted directory is safely re-enumerated.
type Crawler struct {
	store                    *Store
	agent, root, key, active string
	dir                      *os.File
	RescanInterval           time.Duration
	watch                    *discoveryWatch
	watchRequested           bool
	nextWatchRetry           time.Time
	nextProbe                time.Time
	probeBefore              int64
	readProgress             map[string]readProgress
}

type readProgress struct{ at, offset, revision int64 }

// Collect batches scheduling markers only when the durable checkpoint is unchanged.
func (c *Crawler) Collect(ctx context.Context, source agentlog.Source, budget agentlog.Budget, since time.Time) (Checkpoint, error) {
	if source.Root != c.root || source.Agent != c.agent {
		return Checkpoint{}, ErrInvalid
	}
	return c.store.collect(ctx, source, budget, since, c)
}

// Losing an unflushed marker only repeats a read from the already durable checkpoint.
func (c *Crawler) FlushReadProgress(ctx context.Context) error {
	c.store.mu.Lock()
	defer c.store.mu.Unlock()
	if len(c.readProgress) == 0 {
		return nil
	}
	tx, err := c.store.db.BeginTx(ctx, nil)
	if err != nil {
		return storageError(err)
	}
	defer tx.Rollback()
	args := make([]any, 0, 4*len(c.readProgress))
	for id, progress := range c.readProgress {
		args = append(args, id, progress.at, progress.offset, progress.revision)
	}
	// Bound SQL parameters while keeping cancellation and revision checks per batch.
	for start := 0; start < len(args); start += 512 {
		end := min(start+512, len(args))
		values := strings.TrimSuffix(strings.Repeat("(?,?,?,?),", (end-start)/4), ",")
		query := `WITH progress(id,at,offset,revision) AS (VALUES ` + values + `)
UPDATE discovery_files SET read_ns=progress.at,pending=CASE WHEN size>progress.offset THEN 1 ELSE 0 END
FROM progress WHERE discovery_files.id=progress.id
AND EXISTS(SELECT 1 FROM sources WHERE sources.id=progress.id AND sources.revision=progress.revision)`
		if _, err = tx.ExecContext(ctx, query, args[start:end]...); err != nil {
			return storageError(err)
		}
	}
	if _, err = tx.ExecContext(ctx, `DELETE FROM metadata WHERE key='intake_code'`); err != nil {
		return storageError(err)
	}
	if err = tx.Commit(); err != nil {
		return storageError(err)
	}
	clear(c.readProgress)
	return nil
}

type DiscoveryProgress struct {
	Known              int      `json:"known_sources"`
	Pending            int      `json:"pending_sources"`
	Directories        int      `json:"pending_directories"`
	Entries            int      `json:"scanned_entries"`
	Status             string   `json:"status"`
	Reasons            []string `json:"reason_codes"`
	HistoricalMissing  int      `json:"historical_missing"`
	UnreadMissing      int      `json:"unread_missing"`
	MissingDirectories int      `json:"missing_directories"`
}

func (s *Store) NewCrawler(agent, root string) (*Crawler, error) {
	source, err := agentlog.NewSource(agent, root, root)
	if err != nil {
		return nil, err
	}
	result, err := s.db.Exec(`INSERT OR IGNORE INTO discovery_dirs(root_key,path) SELECT ?,? WHERE (SELECT count(*) FROM discovery_dirs)<8192 OR EXISTS(SELECT 1 FROM discovery_dirs WHERE root_key=? AND path=?)`, source.ID, root, source.ID, root)
	if err == nil {
		if n, _ := result.RowsAffected(); n == 0 {
			var count int
			err = s.db.QueryRow("SELECT count(*) FROM discovery_dirs WHERE root_key=? AND path=?", source.ID, root).Scan(&count)
			if err == nil && count == 0 {
				err = ErrCapacity
			}
		}
	}
	return &Crawler{store: s, agent: agent, root: root, key: source.ID, RescanInterval: 30 * time.Second}, err
}
func (c *Crawler) Close() {
	c.closeDirectory()
	if c.watch != nil {
		c.watch.close()
		c.watch = nil
	}
	c.watchRequested = false
}
func (c *Crawler) closeDirectory() {
	if c.dir != nil {
		c.dir.Close()
		c.dir = nil
	}
}
func discoveryReason(err error) string {
	if errors.Is(err, os.ErrNotExist) {
		return "aidr_log_source_missing"
	}
	if errors.Is(err, os.ErrPermission) {
		return "aidr_log_permission_denied"
	}
	return "aidr_log_io_error"
}
func safeInfo(path string) (os.FileInfo, error) {
	for p := filepath.Dir(path); ; p = filepath.Dir(p) {
		i, e := os.Lstat(p)
		if e != nil {
			return nil, e
		}
		if i.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("aidr_log_symlink")
		}
		if p == filepath.Dir(p) {
			break
		}
	}
	info, err := os.Lstat(path)
	if err == nil && info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("aidr_log_symlink")
	}
	return info, err
}

// Step bounds entries, discovered files, metadata probes and elapsed time.
// It never resets the catalogue to the first page returned by enumeration.
func (c *Crawler) Step(ctx context.Context, maxFiles, maxEntries int, budget time.Duration) (progress DiscoveryProgress, resultErr error) {
	defer func() { resultErr = storageError(resultErr) }()
	p := DiscoveryProgress{Status: "complete", Reasons: []string{}}
	if maxFiles < 1 || maxFiles > 4096 || maxEntries < 1 || maxEntries > 10000 || budget <= 0 || budget > time.Second {
		return p, ErrInvalid
	}
	deadline := time.Now().Add(budget)
	changes := c.prepareProbes()
	c.store.mu.Lock()
	defer c.store.mu.Unlock()
	db, err := c.store.db.BeginTx(ctx, nil)
	if err != nil {
		return p, err
	}
	defer func() {
		db.Rollback()
		if resultErr != nil {
			c.closeDirectory() // Retry enumeration from its persisted position after rollback.
			if c.watch != nil {
				c.watch.dirty.Store(true)
			}
		}
	}()
	for path, op := range changes {
		if _, err = db.ExecContext(ctx, `UPDATE discovery_files SET probe_ns=min(probe_ns,?),pending=1 WHERE root_key=? AND path=?`, c.probeBefore-1, c.key, path); err != nil {
			return p, err
		}
		result, e := db.ExecContext(ctx, `UPDATE discovery_dirs SET probe_ns=0,visited_ns=0 WHERE root_key=? AND path=?`, c.key, path)
		if e != nil {
			return p, e
		}
		if op&(fsnotify.Create|fsnotify.Remove|fsnotify.Rename) != 0 {
			if _, err = db.ExecContext(ctx, `UPDATE discovery_dirs SET probe_ns=0,visited_ns=0 WHERE root_key=? AND path=?`, c.key, filepath.Dir(path)); err != nil {
				return p, err
			}
			if n, _ := result.RowsAffected(); n > 0 {
				prefix := path + string(filepath.Separator)
				if _, err = db.ExecContext(ctx, `UPDATE discovery_files SET probe_ns=min(probe_ns,?),pending=1 WHERE root_key=? AND instr(path,?)=1`, c.probeBefore-1, c.key, prefix); err != nil {
					return p, err
				}
			}
		}
	}
	if err := c.probeFiles(ctx, db, time.Now().Add(budget/3)); err != nil {
		return p, err
	}
	// Probe old-date directories too: appends don't update their creation date.
	rows, err := db.QueryContext(ctx, `SELECT path,mtime_ns FROM discovery_dirs WHERE root_key=? AND probe_ns<? ORDER BY probe_ns,path LIMIT 64`, c.key, c.probeBefore)
	if err != nil {
		return p, err
	}
	type directory struct {
		path  string
		mtime int64
	}
	dirs := []directory{}
	for rows.Next() {
		var d directory
		if err = rows.Scan(&d.path, &d.mtime); err != nil {
			rows.Close()
			return p, err
		}
		dirs = append(dirs, d)
	}
	rows.Close()
	for _, d := range dirs {
		if time.Now().After(deadline) {
			break
		}
		st, e := safeInfo(d.path)
		code := ""
		mt := d.mtime
		if e != nil {
			code = discoveryReason(e)
		} else {
			mt = st.ModTime().UnixNano()
			c.watchDirectory(d.path)
		}
		_, err = db.ExecContext(ctx, `UPDATE discovery_dirs SET probe_ns=?,mtime_ns=?,reason=CASE WHEN ?!='' THEN ? ELSE reason END,visited_ns=CASE WHEN mtime_ns!=? THEN 0 ELSE visited_ns END WHERE root_key=? AND path=?`, time.Now().UnixNano(), mt, code, code, mt, c.key, d.path)
		if err != nil {
			return p, err
		}
	}
	files := 0
	for p.Entries < maxEntries && files < maxFiles && time.Now().Before(deadline) && ctx.Err() == nil {
		if c.dir == nil {
			err = db.QueryRowContext(ctx, `SELECT path FROM discovery_dirs WHERE root_key=? AND (visited_ns=0 OR visited_ns<?) ORDER BY visited_ns,mtime_ns DESC,path LIMIT 1`, c.key, time.Now().Add(-c.RescanInterval).UnixNano()).Scan(&c.active)
			if errors.Is(err, sql.ErrNoRows) {
				break
			}
			if err != nil {
				return p, err
			}
			_, e := safeInfo(c.active)
			if e == nil {
				c.dir, e = os.Open(c.active)
				if e == nil {
					_, e = db.ExecContext(ctx, "UPDATE discovery_dirs SET reason='' WHERE root_key=? AND path=?", c.key, c.active)
				}
			}
			if e != nil {
				_, err = db.ExecContext(ctx, `UPDATE discovery_dirs SET visited_ns=?,reason=? WHERE root_key=? AND path=?`, time.Now().UnixNano(), discoveryReason(e), c.key, c.active)
				if err != nil {
					return p, err
				}
				p.Entries++
				continue
			}
		}
		names, e := c.dir.Readdirnames(1)
		if e == io.EOF {
			c.closeDirectory()
			_, err = db.ExecContext(ctx, `UPDATE discovery_dirs SET visited_ns=? WHERE root_key=? AND path=?`, time.Now().UnixNano(), c.key, c.active)
			if err != nil {
				return p, err
			}
			continue
		}
		if e != nil {
			c.closeDirectory()
			_, err = db.ExecContext(ctx, `UPDATE discovery_dirs SET visited_ns=?,reason=? WHERE root_key=? AND path=?`, time.Now().UnixNano(), discoveryReason(e), c.key, c.active)
			if err != nil {
				return p, err
			}
			p.Entries++
			continue
		}
		p.Entries++
		full := filepath.Join(c.active, names[0])
		st, e := os.Lstat(full)
		if e != nil {
			if _, err = db.ExecContext(ctx, "UPDATE discovery_dirs SET reason=? WHERE root_key=? AND path=?", discoveryReason(e), c.key, c.active); err != nil {
				return p, err
			}
			continue
		}
		if st.Mode()&os.ModeSymlink != 0 {
			if _, err = db.ExecContext(ctx, "UPDATE discovery_dirs SET reason='aidr_log_symlink' WHERE root_key=? AND path=?", c.key, c.active); err != nil {
				return p, err
			}
			continue
		}
		if len(full) > 4096 || strings.Count(strings.TrimPrefix(full, c.root), string(filepath.Separator)) > 32 {
			if _, err = db.ExecContext(ctx, "UPDATE discovery_dirs SET reason='aidr_log_discovery_depth' WHERE root_key=? AND path=?", c.key, c.active); err != nil {
				return p, err
			}
			continue
		}
		if st.IsDir() {
			var result sql.Result
			result, err = db.ExecContext(ctx, `INSERT OR IGNORE INTO discovery_dirs(root_key,path,mtime_ns) SELECT ?,?,? WHERE (SELECT count(*) FROM discovery_dirs)<8192`, c.key, full, st.ModTime().UnixNano())
			if err == nil {
				if n, _ := result.RowsAffected(); n > 0 {
					c.watchDirectory(full)
				}
			}
		} else if st.Mode().IsRegular() && agentlog.SourceFile(c.agent, c.root, full) {
			files++
			src, _ := agentlog.NewSource(c.agent, c.root, full)
			_, err = db.ExecContext(ctx, `INSERT INTO discovery_files(id,root_key,agent,root,path,mtime_ns,size) SELECT ?,?,?,?,?,?,? WHERE (SELECT count(*) FROM discovery_files)<? OR EXISTS(SELECT 1 FROM discovery_files WHERE id=?) ON CONFLICT(id) DO UPDATE SET pending=1,mtime_ns=excluded.mtime_ns,size=excluded.size WHERE mtime_ns!=excluded.mtime_ns OR size!=excluded.size`, src.ID, c.key, c.agent, c.root, full, st.ModTime().UnixNano(), st.Size(), c.store.limits.Sources, src.ID)
		}
		if err != nil {
			return p, err
		}
	}
	if ctx.Err() != nil {
		return p, ctx.Err()
	}
	var n, total int
	if err = db.QueryRowContext(ctx, `SELECT count(*),coalesce(sum(pending),0),
 (SELECT count(*) FROM discovery_dirs WHERE root_key=? AND visited_ns=0),
 (SELECT count(*) FROM discovery_dirs),(SELECT count(*) FROM discovery_files),
 (SELECT count(*) FROM discovery_dirs WHERE root_key=? AND reason='aidr_log_source_missing')
 FROM discovery_files WHERE root_key=?`, c.key, c.key, c.key).Scan(&p.Known, &p.Pending, &p.Directories, &n, &total, &p.MissingDirectories); err != nil {
		return p, err
	}
	if c.dir != nil || p.Directories > 0 {
		p.Reasons = appendUnique(p.Reasons, "aidr_log_discovery_pending")
	}
	if files == maxFiles || p.Entries == maxEntries || time.Now().After(deadline) {
		p.Reasons = appendUnique(p.Reasons, "aidr_log_discovery_budget")
	}
	if n >= 8192 || total >= c.store.limits.Sources {
		p.Reasons = appendUnique(p.Reasons, "aidr_log_discovery_capacity")
	}
	const historical = `f.reason='aidr_log_source_missing' AND s.id IS NOT NULL AND CAST(json_extract(s.cursor,'$.offset') AS INTEGER)>=f.size`
	sourceIndex := ""
	if c.store.maintenanceIndexed {
		sourceIndex = " INDEXED BY sources_discovery"
	}
	sourceJoin := ` LEFT JOIN sources s` + sourceIndex + ` ON s.id=f.id AND json_extract(s.cursor,'$.context_repair') IS NULL `
	var historicalPending int
	err = db.QueryRowContext(ctx, `SELECT coalesce(sum(CASE WHEN `+historical+` THEN 1 ELSE 0 END),0),coalesce(sum(CASE WHEN NOT coalesce((`+historical+`),0) THEN 1 ELSE 0 END),0),coalesce(sum(CASE WHEN `+historical+` AND f.pending=1 THEN 1 ELSE 0 END),0) FROM discovery_files f`+sourceJoin+`WHERE f.root_key=? AND f.reason='aidr_log_source_missing'`, c.key).Scan(&p.HistoricalMissing, &p.UnreadMissing, &historicalPending)
	if err != nil {
		return p, err
	}
	p.Pending -= historicalPending
	rows, err = db.QueryContext(ctx, `SELECT DISTINCT reason FROM discovery_dirs WHERE root_key=? AND reason!='' UNION SELECT DISTINCT f.reason FROM discovery_files f`+sourceJoin+`WHERE f.root_key=? AND f.reason!='' AND NOT coalesce((`+historical+`),0)`, c.key, c.key)
	if err != nil {
		return p, err
	}
	for rows.Next() {
		var code string
		rows.Scan(&code)
		p.Reasons = appendUnique(p.Reasons, code)
	}
	rows.Close()
	if len(p.Reasons) > 0 {
		p.Status = "partial"
	}
	return p, db.Commit()
}
func appendUnique(values []string, value string) []string {
	for _, v := range values {
		if v == value {
			return values
		}
	}
	if len(values) < 16 {
		return append(values, value)
	}
	return values
}
func (c *Crawler) probeFiles(ctx context.Context, db *sql.Tx, deadline time.Time) error {
	rows, err := db.QueryContext(ctx, `SELECT id,path,mtime_ns,size,read_ns,reason FROM discovery_files WHERE root_key=? AND probe_ns<? ORDER BY probe_ns,id LIMIT 128`, c.key, c.probeBefore)
	if err != nil {
		return err
	}
	type file struct {
		id, path, reason  string
		mtime, size, read int64
	}
	fs := []file{}
	for rows.Next() {
		var f file
		if err = rows.Scan(&f.id, &f.path, &f.mtime, &f.size, &f.read, &f.reason); err != nil {
			rows.Close()
			return err
		}
		fs = append(fs, f)
	}
	rows.Close()
	args := make([]any, 0, 6*len(fs))
	for _, f := range fs {
		if time.Now().After(deadline) {
			break
		}
		st, e := safeInfo(f.path)
		mt, size := f.mtime, f.size
		code := ""
		dirty := 0
		// Revalidate file identity/anchors even after same-size, same-mtime replacement.
		if f.read < time.Now().Add(-c.RescanInterval).UnixNano() {
			dirty = 1
		}
		if e != nil {
			code = discoveryReason(e)
			dirty = 1
		} else {
			mt, size = st.ModTime().UnixNano(), st.Size()
			if mt != f.mtime || size != f.size {
				dirty = 1
			}
		}
		if code != f.reason {
			dirty = 1
		}
		// A new failure or recovery is eligible immediately; unchanged missing files retry on the rescan interval.
		args = append(args, f.id, time.Now().UnixNano(), mt, size, dirty, code)
	}
	if len(args) == 0 {
		return nil
	}
	values := strings.TrimSuffix(strings.Repeat("(?,?,?,?,?,?),", len(args)/6), ",")
	_, err = db.ExecContext(ctx, `WITH probes(id,at,mtime,size,dirty,reason) AS (VALUES `+values+`)
UPDATE discovery_files SET probe_ns=probes.at,mtime_ns=probes.mtime,size=probes.size,
pending=CASE WHEN probes.dirty=1 THEN 1 ELSE pending END,
read_ns=CASE WHEN discovery_files.reason!=probes.reason THEN 0 ELSE read_ns END,reason=probes.reason
FROM probes WHERE discovery_files.id=probes.id`, args...)
	return err
}

// Separate recent activity from fair backlog intake; both retain read cursors.
func (c *Crawler) Ready(ctx context.Context, recent bool, limit int) ([]agentlog.Source, error) {
	if limit < 1 || limit > 32 {
		return nil, ErrInvalid
	}
	c.store.mu.Lock()
	defer c.store.mu.Unlock()
	c.store.readCheckpoints = nil
	comparison := "<"
	if recent {
		comparison = ">="
	}
	rows, err := c.store.db.QueryContext(ctx, `SELECT d.id,d.agent,d.root,d.path,s.revision,s.cursor,s.coverage FROM discovery_files d LEFT JOIN sources s ON s.id=d.id WHERE d.root_key=? AND d.pending=1 AND d.mtime_ns `+comparison+` ? AND (d.reason!='aidr_log_source_missing' OR d.read_ns<?) ORDER BY d.read_ns,d.mtime_ns DESC,d.id LIMIT ?`, c.key, time.Now().Add(-15*time.Minute).UnixNano(), time.Now().Add(-c.RescanInterval).UnixNano(), limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []agentlog.Source{}
	checkpoints := make(map[string]Checkpoint)
	checkpointBytes := 0
	for rows.Next() {
		var src agentlog.Source
		var revision sql.NullInt64
		var cursor, coverage sql.NullString
		if err = rows.Scan(&src.ID, &src.Agent, &src.Root, &src.Path, &revision, &cursor, &coverage); err != nil {
			return nil, err
		}
		if revision.Valid && checkpointBytes+len(cursor.String)+len(coverage.String) <= 1<<20 {
			cp := Checkpoint{Revision: revision.Int64}
			if !cursor.Valid || !coverage.Valid || json.Unmarshal([]byte(cursor.String), &cp.Cursor) != nil || json.Unmarshal([]byte(coverage.String), &cp.Coverage) != nil {
				return nil, errors.New("aidr_store_corrupt")
			}
			checkpoints[src.ID] = cp
			checkpointBytes += len(cursor.String) + len(coverage.String)
		}
		out = append(out, src)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	c.store.readCheckpoints = checkpoints
	return out, nil
}

const discoveryReadDoneSQL = `UPDATE discovery_files SET read_ns=?,pending=CASE WHEN size>? THEN 1 ELSE 0 END WHERE id=?`

func (c *Crawler) ReadDone(ctx context.Context, src agentlog.Source, offset int64) error {
	_, err := c.store.db.ExecContext(ctx, discoveryReadDoneSQL, time.Now().UnixNano(), offset, src.ID)
	return err
}
