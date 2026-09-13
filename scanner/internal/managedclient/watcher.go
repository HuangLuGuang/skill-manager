package managedclient

import (
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
)

var ignoredWatchDirs = map[string]bool{
	".git": true, ".venv": true, "node_modules": true,
	"__pycache__": true, "dist": true, "build": true,
}

type SkillWatcher struct {
	watcher *fsnotify.Watcher
	changes chan struct{}
	done    chan struct{}
	watched map[string]bool
	roots   map[string]bool
	mu      sync.Mutex
}

func NewSkillWatcher() (*SkillWatcher, error) {
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, err
	}
	result := &SkillWatcher{
		watcher: watcher,
		changes: make(chan struct{}, 1),
		done:    make(chan struct{}),
		watched: map[string]bool{},
		roots:   map[string]bool{},
	}
	go result.run()
	return result, nil
}

func (watcher *SkillWatcher) Changes() <-chan struct{} { return watcher.changes }

func (watcher *SkillWatcher) Close() error {
	close(watcher.done)
	return watcher.watcher.Close()
}

func (watcher *SkillWatcher) Refresh(home string, store *Store) error {
	roots := managedSkillsRoots(home)
	for _, spec := range adaptersForHome(home) {
		for _, root := range spec.skillRoots {
			roots = append(roots, resolveSkillRoot(home, root))
		}
	}
	if config, err := LoadConfig(home); err == nil {
		for _, agent := range config.CustomAgents {
			roots = append(roots, agent.SkillsPath)
		}
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
			if event.Op&fsnotify.Create != 0 {
				if info, err := os.Stat(event.Name); err == nil && info.IsDir() && !ignoredWatchPath(event.Name) {
					_ = watcher.addTree(event.Name)
				}
			}
			if timer == nil {
				timer = time.NewTimer(time.Second)
			} else {
				if !timer.Stop() {
					select {
					case <-timer.C:
					default:
					}
				}
				timer.Reset(time.Second)
			}
			timerC = timer.C
		case _, ok := <-watcher.watcher.Errors:
			if !ok {
				return
			}
			select {
			case watcher.changes <- struct{}{}:
			default:
			}
		case <-timerC:
			select {
			case watcher.changes <- struct{}{}:
			default:
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
