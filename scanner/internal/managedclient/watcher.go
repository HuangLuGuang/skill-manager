package managedclient

import (
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
)

var ignoredWatchDirs = map[string]bool{
	".git": true, ".venv": true, "node_modules": true,
	"__pycache__": true, "dist": true, "build": true,
}

// Editors commonly emit several write/rename events for one save. Keep a
// short stability window, but leave patrol scheduling to the daemon instead
// of adding a second debounce there.
const skillWatchDebounce = 300 * time.Millisecond

type SkillWatcher struct {
	watcher    *fsnotify.Watcher
	changes    chan []string
	done       chan struct{}
	watched    map[string]bool
	roots      map[string]bool
	suppressed map[string]time.Time
	mu         sync.Mutex
}

func NewSkillWatcher() (*SkillWatcher, error) {
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, err
	}
	result := &SkillWatcher{
		watcher:    watcher,
		changes:    make(chan []string, 1),
		done:       make(chan struct{}),
		watched:    map[string]bool{},
		roots:      map[string]bool{},
		suppressed: map[string]time.Time{},
	}
	go result.run()
	return result, nil
}

func (watcher *SkillWatcher) Changes() <-chan []string { return watcher.changes }

func (watcher *SkillWatcher) SuppressRoots(paths []string, duration time.Duration) {
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	until := time.Now().Add(duration)
	for _, path := range paths {
		if path != "" {
			watcher.suppressed[filepath.Clean(path)] = until
		}
	}
}

func (watcher *SkillWatcher) suppressedPath(path string) bool {
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	now := time.Now()
	for root, until := range watcher.suppressed {
		if now.After(until) {
			delete(watcher.suppressed, root)
			continue
		}
		if pathWithinLexical(path, root) || filepath.Clean(path) == root {
			return true
		}
	}
	return false
}

func (watcher *SkillWatcher) Close() error {
	close(watcher.done)
	return watcher.watcher.Close()
}

func (watcher *SkillWatcher) Refresh(home string, store *Store) error {
	config, err := LoadConfig(home)
	if err != nil {
		return err
	}
	roots := managedSkillsRoots(home)
	for _, spec := range adaptersForHome(home) {
		skillRoots := spec.skillRoots
		if configured := config.AgentSkillRoots[spec.agentType]; len(configured) > 0 {
			skillRoots = configured
		}
		for _, root := range skillRoots {
			pattern := resolveSkillRoot(home, root)
			if wildcard := strings.IndexAny(pattern, "*?["); wildcard >= 0 {
				prefix := pattern[:wildcard]
				if strings.HasSuffix(prefix, string(filepath.Separator)) {
					prefix = filepath.Clean(prefix)
				} else {
					prefix = filepath.Dir(prefix)
				}
				roots = append(roots, prefix)
				matches, _ := filepath.Glob(pattern)
				roots = append(roots, matches...)
				continue
			}
			roots = append(roots, pattern)
		}
	}
	for _, agent := range config.CustomAgents {
		roots = append(roots, agent.SkillsPath)
	}
	if installs, err := store.Installations(); err == nil {
		for _, install := range installs {
			roots = append(roots, filepath.Dir(install.TargetPath))
			if resolved, resolveErr := filepath.EvalSymlinks(install.TargetPath); resolveErr == nil {
				roots = append(roots, resolved)
			}
		}
	}
	for _, root := range roots {
		watcher.mu.Lock()
		watcher.roots[filepath.Clean(root)] = true
		watcher.mu.Unlock()
		if err := watcher.addRoot(root); err != nil {
			return err
		}
	}
	return nil
}

func (watcher *SkillWatcher) addRoot(root string) error {
	root = filepath.Clean(root)
	if info, err := os.Stat(root); err == nil && info.IsDir() {
		return watcher.addTree(root)
	}
	parent := root
	for {
		next := filepath.Dir(parent)
		if next == parent {
			return nil
		}
		parent = next
		if info, err := os.Stat(parent); err == nil && info.IsDir() {
			return watcher.add(parent)
		}
	}
}

func (watcher *SkillWatcher) addTree(root string) error {
	return filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if !entry.IsDir() {
			return nil
		}
		if path != root && ignoredWatchDirs[entry.Name()] {
			return filepath.SkipDir
		}
		return watcher.add(path)
	})
}

func (watcher *SkillWatcher) add(path string) error {
	path = filepath.Clean(path)
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	if watcher.watched[path] {
		return nil
	}
	if err := watcher.watcher.Add(path); err != nil {
		return err
	}
	watcher.watched[path] = true
	return nil
}

func (watcher *SkillWatcher) run() {
	var timer *time.Timer
	var timerC <-chan time.Time
	pending := map[string]bool{}
	for {
		select {
		case <-watcher.done:
			if timer != nil {
				timer.Stop()
			}
			return
		case event, ok := <-watcher.watcher.Events:
			if !ok {
				return
			}
			if event.Op&(fsnotify.Create|fsnotify.Write|fsnotify.Remove|fsnotify.Rename) == 0 {
				continue
			}
			if !watcher.relevant(event.Name) {
				continue
			}
			pending[filepath.Clean(event.Name)] = true
			if event.Op&fsnotify.Create != 0 {
				if info, err := os.Stat(event.Name); err == nil && info.IsDir() && !ignoredWatchPath(event.Name) {
					_ = watcher.addTree(event.Name)
				}
			}
			if timer == nil {
				timer = time.NewTimer(skillWatchDebounce)
			} else {
				if !timer.Stop() {
					select {
					case <-timer.C:
					default:
					}
				}
				timer.Reset(skillWatchDebounce)
			}
			timerC = timer.C
		case _, ok := <-watcher.watcher.Errors:
			if !ok {
				return
			}
			select {
			case watcher.changes <- nil:
			default:
			}
		case <-timerC:
			paths := make([]string, 0, len(pending))
			for path := range pending {
				if !watcher.suppressedPath(path) {
					paths = append(paths, path)
				}
			}
			sort.Strings(paths)
			pending = map[string]bool{}
			if len(paths) > 0 {
				select {
				case watcher.changes <- paths:
				default:
				}
			}
			timerC = nil
		}
	}
}

func (watcher *SkillWatcher) relevant(path string) bool {
	path = filepath.Clean(path)
	watcher.mu.Lock()
	defer watcher.mu.Unlock()
	for root := range watcher.roots {
		if path == root || strings.HasPrefix(path, root+string(filepath.Separator)) || strings.HasPrefix(root, path+string(filepath.Separator)) {
			return true
		}
	}
	return false
}

func ignoredWatchPath(path string) bool {
	for _, part := range strings.Split(filepath.Clean(path), string(filepath.Separator)) {
		if ignoredWatchDirs[part] {
			return true
		}
	}
	return false
}
