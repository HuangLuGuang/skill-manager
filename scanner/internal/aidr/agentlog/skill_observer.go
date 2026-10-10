package agentlog

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"skill-manager/scanner/internal/manifest"
)

type skillFile struct {
	info   os.FileInfo
	change int64
}

type skillCacheKey struct {
	root                  string
	mode                  string
	age, files            int
	fileBytes, totalBytes int64
}

type skillObservation struct {
	digest, observed, status, reason string
	files                            map[string]skillFile
	used, expires                    time.Time
}

type skillFlight struct {
	done   chan struct{}
	result skillObservation
}

// One observer is owned by one device-bound collector. Its cache is bounded by
// both directories and file metadata; concurrent readers share the same job.
type SkillObserver struct {
	mu                            sync.Mutex
	cache                         map[skillCacheKey]skillObservation
	flights                       map[skillCacheKey]*skillFlight
	changed                       chan struct{}
	active                        int
	now                           func() time.Time
	reads, bytes, hits, coalesced atomic.Int64
}

type SkillObserverStats struct{ FileReads, BytesRead, CacheHits, Coalesced int64 }

func NewSkillObserver() *SkillObserver {
	return &SkillObserver{cache: make(map[skillCacheKey]skillObservation), flights: make(map[skillCacheKey]*skillFlight), changed: make(chan struct{}), now: time.Now}
}

func (o *SkillObserver) Stats() SkillObserverStats {
	return SkillObserverStats{o.reads.Load(), o.bytes.Load(), o.hits.Load(), o.coalesced.Load()}
}

func (o *SkillObserver) Observe(ctx context.Context, use *SkillUse, policy *AuditPolicy) {
	if use == nil || use.Path == "" {
		return
	}
	use.Digest, use.CheckedAt, use.ContentStatus, use.ContentReason = "", "", "", ""
	p := DefaultSkillAuditPolicy()
	negotiated := policy != nil && policy.SkillAudit != nil
	if negotiated {
		p = *policy.SkillAudit
	} else {
		p.CheckMode = "every_use"
	}
	if !p.Enabled {
		if negotiated {
			use.ContentStatus, use.ContentReason = "disabled", "audit_disabled"
		}
		return
	}
	key := skillCacheKey{filepath.Dir(filepath.FromSlash(use.Path)), p.CheckMode, p.DigestCacheSeconds, p.MaxFiles, p.MaxFileBytes, p.MaxTotalBytes}
	result := o.observe(ctx, key, p.MaxConcurrency)
	use.Digest, use.CheckedAt = result.digest, result.observed
	if negotiated {
		use.ContentStatus, use.ContentReason = result.status, result.reason
	}
}

func unavailable(reason string) skillObservation {
	return skillObservation{status: "unavailable", reason: reason}
}

func (o *SkillObserver) observe(ctx context.Context, key skillCacheKey, concurrency int) skillObservation {
	for {
		if ctx.Err() != nil {
			return unavailable("check_cancelled")
		}
		o.mu.Lock()
		if flight := o.flights[key]; flight != nil {
			o.coalesced.Add(1)
			o.mu.Unlock()
			select {
			case <-ctx.Done():
				return unavailable("check_cancelled")
			case <-flight.done:
				result := flight.result
				if result.digest != "" {
					result.status = "reused"
				}
				return result
			}
		}
		if o.active >= concurrency {
			changed := o.changed
			o.mu.Unlock()
			select {
			case <-ctx.Done():
				return unavailable("check_cancelled")
			case <-changed:
				continue
			}
		}
		flight := &skillFlight{done: make(chan struct{})}
		o.flights[key] = flight
		o.active++
		cached := o.cache[key]
		o.mu.Unlock()
		result := o.read(ctx, key, cached)
		o.mu.Lock()
		delete(o.cache, key)
		if result.digest != "" && len(result.files) <= 8192 {
			files := len(result.files)
			for _, entry := range o.cache {
				files += len(entry.files)
			}
			for len(o.cache) >= 128 || files > 8192 {
				var oldest skillCacheKey
				var at time.Time
				for k, v := range o.cache {
					if at.IsZero() || v.used.Before(at) {
						oldest, at = k, v.used
					}
				}
				files -= len(o.cache[oldest].files)
				delete(o.cache, oldest)
			}
			o.cache[key] = result
		}
		flight.result = result
		delete(o.flights, key)
		o.active--
		close(flight.done)
		close(o.changed)
		o.changed = make(chan struct{})
		o.mu.Unlock()
		return result
	}
}

func sameSkillFile(a, b skillFile) bool {
	return a.info != nil && b.info != nil && os.SameFile(a.info, b.info) && a.info.Mode() == b.info.Mode() && a.info.Size() == b.info.Size() && a.info.ModTime().Equal(b.info.ModTime()) && a.change == b.change
}

func sameSkillTree(a, b map[string]skillFile) bool {
	if len(a) != len(b) {
		return false
	}
	for path, info := range a {
		if !sameSkillFile(info, b[path]) {
			return false
		}
	}
	return true
}

var skillIgnored = map[string]bool{".git": true, ".venv": true, "node_modules": true, "__pycache__": true, "dist": true, "build": true, ".DS_Store": true}

func skillReadReason(err error) string {
	if errors.Is(err, os.ErrNotExist) {
		return "source_missing"
	}
	if err != nil && err.Error() == "aidr_log_symlink" {
		return "source_symlink"
	}
	return "source_unreadable"
}

// Read directory entries in bounded chunks instead of allocating an unbounded
// directory listing. Metadata is checked on every use, even on a digest hit.
func skillTree(ctx context.Context, key skillCacheKey) (map[string]skillFile, string) {
	if err := checkPath(filepath.Join(key.root, "SKILL.md")); err != nil {
		return nil, skillReadReason(err)
	}
	files := make(map[string]skillFile)
	var total int64
	entries := 0
	var walk func(string) string
	walk = func(dir string) string {
		if ctx.Err() != nil {
			return "check_cancelled"
		}
		if err := checkPath(dir); err != nil {
			return skillReadReason(err)
		}
		f, err := openLog(dir)
		if err != nil {
			return skillReadReason(err)
		}
		defer f.Close()
		for {
			batch, err := f.ReadDir(64)
			if err != nil && err != io.EOF {
				return skillReadReason(err)
			}
			for _, entry := range batch {
				if ctx.Err() != nil {
					return "check_cancelled"
				}
				entries++
				if entries > key.files*4+256 {
					return "entry_limit"
				}
				if skillIgnored[entry.Name()] {
					continue
				}
				path := filepath.Join(dir, entry.Name())
				info, e := os.Lstat(path)
				if e != nil {
					return skillReadReason(e)
				}
				if info.Mode()&os.ModeSymlink != 0 {
					return "source_symlink"
				}
				if info.IsDir() {
					if reason := walk(path); reason != "" {
						return reason
					}
					continue
				}
				if !info.Mode().IsRegular() {
					return "source_unreadable"
				}
				if len(files) >= key.files {
					return "file_limit"
				}
				if info.Size() > key.fileBytes {
					return "file_size_limit"
				}
				total += info.Size()
				if total > key.totalBytes {
					return "total_size_limit"
				}
				rel, e := filepath.Rel(key.root, path)
				if e != nil {
					return "source_unreadable"
				}
				files[filepath.ToSlash(rel)] = skillFile{info, skillChangeTime(info)}
			}
			if err == io.EOF {
				break
			}
		}
		return ""
	}
	if reason := walk(key.root); reason != "" {
		return nil, reason
	}
	if _, ok := files["SKILL.md"]; !ok {
		return nil, "source_missing"
	}
	return files, ""
}

func (o *SkillObserver) read(ctx context.Context, key skillCacheKey, cached skillObservation) skillObservation {
	files, reason := skillTree(ctx, key)
	if reason != "" {
		return unavailable(reason)
	}
	now := o.now()
	if key.mode == "on_change" && cached.digest != "" && now.Before(cached.expires) && sameSkillTree(files, cached.files) {
		cached.status, cached.used = "reused", now
		o.hits.Add(1)
		return cached
	}
	manifestFiles := make([]manifest.FileEntry, 0, len(files))
	buffer := make([]byte, 64<<10)
	for rel, before := range files {
		path := filepath.Join(key.root, filepath.FromSlash(rel))
		if err := checkPath(path); err != nil {
			return unavailable(skillReadReason(err))
		}
		f, err := openLog(path)
		if err != nil {
			return unavailable(skillReadReason(err))
		}
		info, err := f.Stat()
		if err != nil || !sameSkillFile(before, skillFile{info, skillChangeTime(info)}) {
			f.Close()
			return unavailable("source_changed")
		}
		h := sha256.New()
		reader := io.LimitReader(f, before.info.Size()+1)
		var size int64
		o.reads.Add(1)
		for {
			if ctx.Err() != nil {
				f.Close()
				return unavailable("check_cancelled")
			}
			n, e := reader.Read(buffer)
			if n > 0 {
				size += int64(n)
				o.bytes.Add(int64(n))
				h.Write(buffer[:n])
			}
			if e == io.EOF {
				break
			}
			if e != nil {
				f.Close()
				return unavailable(skillReadReason(e))
			}
		}
		after, err := f.Stat()
		f.Close()
		if err != nil || size != before.info.Size() || !sameSkillFile(before, skillFile{after, skillChangeTime(after)}) {
			return unavailable("source_changed")
		}
		manifestFiles = append(manifestFiles, manifest.FileEntry{Path: rel, Size: size, SHA256: hex.EncodeToString(h.Sum(nil))})
	}
	after, reason := skillTree(ctx, key)
	if reason != "" {
		return unavailable(reason)
	}
	if !sameSkillTree(files, after) {
		return unavailable("source_changed")
	}
	now = o.now()
	return skillObservation{digest: manifest.ContentSignature(manifestFiles), observed: now.UTC().Format(time.RFC3339Nano), status: "computed", files: after, used: now, expires: now.Add(time.Duration(key.age) * time.Second)}
}
