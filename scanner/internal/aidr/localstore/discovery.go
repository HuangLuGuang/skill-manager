package localstore

import (
	"context"
	"database/sql"
	"errors"
	"io"
	"os"
	"path/filepath"
	"skill-manager/scanner/internal/aidr/agentlog"
	"strings"
	"time"
)

// The directory frontier and source catalogue are durable; file read cursors
// remain owned by Collect. An interrupted directory is safely re-enumerated.
type Crawler struct {
	store                    *Store
	agent, root, key, active string
	dir                      *os.File
	RescanInterval           time.Duration
}
type DiscoveryProgress struct {
	Known       int      `json:"known_sources"`
	Pending     int      `json:"pending_sources"`
	Directories int      `json:"pending_directories"`
	Entries     int      `json:"scanned_entries"`
	Status      string   `json:"status"`
	Reasons     []string `json:"reason_codes"`
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
	for p := path; ; p = filepath.Dir(p) {
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
	return os.Lstat(path)
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
	db := c.store.db
	if err := c.probeFiles(ctx, time.Now().Add(budget/3)); err != nil {
		return p, err
	}
	// Probe old-date directories too: appends don't update their creation date.
	rows, err := db.QueryContext(ctx, `SELECT path,mtime_ns FROM discovery_dirs WHERE root_key=? ORDER BY probe_ns,path LIMIT 64`, c.key)
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
			c.Close()
			_, err = db.ExecContext(ctx, `UPDATE discovery_dirs SET visited_ns=? WHERE root_key=? AND path=?`, time.Now().UnixNano(), c.key, c.active)
			if err != nil {
				return p, err
			}
			continue
		}
		if e != nil {
			c.Close()
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
			_, err = db.ExecContext(ctx, `INSERT OR IGNORE INTO discovery_dirs(root_key,path,mtime_ns) SELECT ?,?,? WHERE (SELECT count(*) FROM discovery_dirs)<8192`, c.key, full, st.ModTime().UnixNano())
		} else if st.Mode().IsRegular() && agentlog.SourceFile(c.agent, c.root, full) {
			files++
			src, _ := agentlog.NewSource(c.agent, c.root, full)
			_, err = db.ExecContext(ctx, `INSERT INTO discovery_files(id,root_key,agent,root,path,mtime_ns,size) SELECT ?,?,?,?,?,?,? WHERE (SELECT count(*) FROM discovery_files)<? OR EXISTS(SELECT 1 FROM discovery_files WHERE id=?) ON CONFLICT(id) DO UPDATE SET pending=CASE WHEN mtime_ns!=excluded.mtime_ns OR size!=excluded.size THEN 1 ELSE pending END,mtime_ns=excluded.mtime_ns,size=excluded.size`, src.ID, c.key, c.agent, c.root, full, st.ModTime().UnixNano(), st.Size(), c.store.limits.Sources, src.ID)
		}
		if err != nil {
			return p, err
		}
	}
	if ctx.Err() != nil {
		return p, ctx.Err()
	}
	if err = db.QueryRowContext(ctx, `SELECT count(*),coalesce(sum(pending),0) FROM discovery_files WHERE root_key=?`, c.key).Scan(&p.Known, &p.Pending); err != nil {
		return p, err
	}
	if err = db.QueryRowContext(ctx, `SELECT count(*) FROM discovery_dirs WHERE root_key=? AND visited_ns=0`, c.key).Scan(&p.Directories); err != nil {
		return p, err
	}
	if c.dir != nil || p.Directories > 0 {
		p.Reasons = appendUnique(p.Reasons, "aidr_log_discovery_pending")
	}
	if files == maxFiles || p.Entries == maxEntries || time.Now().After(deadline) {
		p.Reasons = appendUnique(p.Reasons, "aidr_log_discovery_budget")
	}
	var n, total int
	if err = db.QueryRowContext(ctx, "SELECT count(*) FROM discovery_dirs").Scan(&n); err != nil {
		return p, err
	}
	if err = db.QueryRowContext(ctx, "SELECT count(*) FROM discovery_files").Scan(&total); err != nil {
		return p, err
	}
	if n >= 8192 || total >= c.store.limits.Sources {
		p.Reasons = appendUnique(p.Reasons, "aidr_log_discovery_capacity")
	}
	rows, err = db.QueryContext(ctx, `SELECT DISTINCT reason FROM discovery_dirs WHERE root_key=? AND reason!='' UNION SELECT DISTINCT reason FROM discovery_files WHERE root_key=? AND reason!=''`, c.key, c.key)
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
	return p, nil
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
func (c *Crawler) probeFiles(ctx context.Context, deadline time.Time) error {
	rows, err := c.store.db.QueryContext(ctx, `SELECT id,path,mtime_ns,size,read_ns FROM discovery_files WHERE root_key=? ORDER BY probe_ns,id LIMIT 128`, c.key)
	if err != nil {
		return err
	}
	type file struct {
		id, path          string
		mtime, size, read int64
	}
	fs := []file{}
	for rows.Next() {
		var f file
		if err = rows.Scan(&f.id, &f.path, &f.mtime, &f.size, &f.read); err != nil {
			rows.Close()
			return err
		}
		fs = append(fs, f)
	}
	rows.Close()
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
		_, err = c.store.db.ExecContext(ctx, `UPDATE discovery_files SET probe_ns=?,mtime_ns=?,size=?,pending=CASE WHEN ?=1 THEN 1 ELSE pending END,reason=? WHERE id=?`, time.Now().UnixNano(), mt, size, dirty, code, f.id)
		if err != nil {
			return err
		}
	}
	return nil
}

// Separate recent activity from fair backlog intake; both retain read cursors.
func (c *Crawler) Ready(ctx context.Context, recent bool, limit int) ([]agentlog.Source, error) {
	if limit < 1 || limit > 32 {
		return nil, ErrInvalid
	}
	comparison := "<"
	if recent {
		comparison = ">="
	}
	rows, err := c.store.db.QueryContext(ctx, `SELECT id,agent,root,path FROM discovery_files WHERE root_key=? AND pending=1 AND mtime_ns `+comparison+` ? ORDER BY read_ns,mtime_ns DESC,id LIMIT ?`, c.key, time.Now().Add(-15*time.Minute).UnixNano(), limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []agentlog.Source{}
	for rows.Next() {
		var src agentlog.Source
		if err = rows.Scan(&src.ID, &src.Agent, &src.Root, &src.Path); err != nil {
			return nil, err
		}
		out = append(out, src)
	}
	return out, rows.Err()
}
func (c *Crawler) ReadDone(ctx context.Context, src agentlog.Source, offset int64) error {
	_, err := c.store.db.ExecContext(ctx, `UPDATE discovery_files SET read_ns=?,pending=CASE WHEN size>? THEN 1 ELSE 0 END WHERE id=?`, time.Now().UnixNano(), offset, src.ID)
	return err
}
