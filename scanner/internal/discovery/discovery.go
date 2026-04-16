package discovery

import (
	"io/fs"
	"path/filepath"
	"sort"
)

type Skill struct {
	Path string `json:"path"`
}

func Find(root string, ignoreDirs map[string]bool) ([]Skill, error) {
	seen := map[string]bool{}
	var skills []Skill
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() {
			if path != root && ignoreDirs[entry.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		if entry.Name() != "SKILL.md" {
			return nil
		}
		dir := filepath.Dir(path)
		if !seen[dir] {
			seen[dir] = true
			skills = append(skills, Skill{Path: dir})
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Slice(skills, func(i, j int) bool {
		return skills[i].Path < skills[j].Path
	})
	return skills, nil
}
