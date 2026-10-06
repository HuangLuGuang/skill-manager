package agentlog

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Discovery struct {
	Sources  []Source `json:"sources"`
	Coverage Coverage `json:"coverage"`
}

// NewSource fixes an explicit allowed root. Symlink components are not accepted.
func NewSource(agent, root, path string) (Source, error) {
	if !validAgent(agent) || !filepath.IsAbs(root) || !filepath.IsAbs(path) {
		return Source{}, errors.New("aidr_log_source_invalid")
	}
	root = filepath.Clean(root)
	path = filepath.Clean(path)
	rel, err := filepath.Rel(root, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return Source{}, errors.New("aidr_log_source_outside_root")
	}
	return Source{ID: digest(agent, path), Agent: agent, Root: root, Path: path}, nil
}
func checkPath(path string) error {
	for p := filepath.Clean(path); ; p = filepath.Dir(p) {
		st, err := os.Lstat(p)
		if err != nil {
			return err
		}
		if st.Mode()&os.ModeSymlink != 0 {
			return errors.New("aidr_log_symlink")
		}
		if filepath.Dir(p) == p {
			return nil
		}
	}
}
func ioReason(err error) string {
	switch {
	case errors.Is(err, os.ErrPermission):
		return "aidr_log_permission_denied"
	case errors.Is(err, os.ErrNotExist):
		return "aidr_log_source_missing"
	default:
		if err != nil && err.Error() == "aidr_log_symlink" {
			return err.Error()
		}
		return "aidr_log_io_error"
	}
}

// Discover bounds directory enumeration as well as returned files. Missing roots
// and empty readable roots have different coverage; no system-wide home scan occurs.
func Discover(ctx context.Context, agent, root string, maxFiles, maxEntries int, duration time.Duration) Discovery {
	result := Discovery{Sources: []Source{}, Coverage: Coverage{Status: "complete", Reasons: []string{}}}
	if !validAgent(agent) || !filepath.IsAbs(root) || maxFiles < 1 || maxFiles > 4096 || maxEntries < 1 || maxEntries > 100000 || duration <= 0 || duration > time.Minute {
		result.Coverage.mark("unavailable", "aidr_log_discovery_budget_invalid")
		return result
	}
	deadline := time.Now().Add(duration)
	visited := 0
	var walk func(string, int)
	walk = func(path string, depth int) {
		if ctx.Err() != nil {
			result.Coverage.mark("partial", "aidr_log_canceled")
			return
		}
		if len(result.Sources) >= maxFiles || visited >= maxEntries || time.Now().After(deadline) || depth > 32 {
			result.Coverage.mark("partial", "aidr_log_discovery_budget")
			return
		}
		if err := checkPath(path); err != nil {
			result.Coverage.mark("partial", ioReason(err))
			return
		}
		f, err := openLog(path)
		if err != nil {
			result.Coverage.mark("partial", ioReason(err))
			return
		}
		defer f.Close()
		info, e := f.Stat()
		if e != nil || !info.IsDir() {
			result.Coverage.mark("unavailable", "aidr_log_not_directory")
			return
		}
		for {
			names, err := f.Readdirnames(64)
			for _, name := range names {
				if visited >= maxEntries || len(result.Sources) >= maxFiles || ctx.Err() != nil || time.Now().After(deadline) {
					result.Coverage.mark("partial", "aidr_log_discovery_budget")
					return
				}
				visited++
				full := filepath.Join(path, name)
				info, e := os.Lstat(full)
				if e != nil {
					result.Coverage.mark("partial", ioReason(e))
					continue
				}
				if info.Mode()&os.ModeSymlink != 0 {
					result.Coverage.mark("partial", "aidr_log_symlink")
					continue
				}
				if info.IsDir() {
					walk(full, depth+1)
				} else if info.Mode().IsRegular() && strings.HasSuffix(name, ".jsonl") {
					src, e := NewSource(agent, root, full)
					if e == nil {
						result.Sources = append(result.Sources, src)
					}
				}
			}
			if err == io.EOF {
				return
			}
			if err != nil {
				result.Coverage.mark("partial", ioReason(err))
				return
			}
		}
	}
	if err := checkPath(root); err != nil {
		result.Coverage.mark("unavailable", ioReason(err))
		return result
	}
	walk(filepath.Clean(root), 0)
	return result
}
