package managedclient

import (
	"os"
	"sort"
)

// Sharing is computed from physical paths, while reported keys retain the
// Agent's local path so callers can display the scope of a particular Skill.
func annotateDiscoverySharing(inventory *Inventory, config Config) {
	roots, skills := map[string]map[string]bool{}, map[string]map[string]bool{}
	add := func(index map[string]map[string]bool, path, reader string) {
		key := canonicalSkillRoot(path)
		if index[key] == nil {
			index[key] = map[string]bool{}
		}
		index[key][reader] = true
	}
	label := func(agent Agent) string {
		if agent.DisplayName != "" {
			return agent.DisplayName
		}
		return agent.AgentType
	}
	for _, agent := range inventory.Agents {
		readers := []string{label(agent)}
		if agent.AgentType == "global-skills" {
			readers, _ = agent.Capabilities["shared_skill_readers"].([]string)
		}
		for _, reader := range readers {
			for _, root := range agentSkillRoots(agent) {
				add(roots, root, reader)
			}
			for _, skill := range agent.Skills {
				add(skills, skill.Path, reader)
			}
		}
	}
	// Duplicate custom roots are represented by their existing directory group.
	for _, custom := range config.CustomAgents {
		if info, err := os.Stat(custom.SkillsPath); err == nil && info.IsDir() {
			add(roots, custom.SkillsPath, custom.Name)
		}
	}
	for i := range inventory.Agents {
		agent := &inventory.Agents[i]
		if agent.Capabilities == nil {
			agent.Capabilities = map[string]any{}
		}
		known, _ := agent.Capabilities["shared_skill_readers"].([]string)
		collect := func(groups ...map[string]bool) []string {
			readers := map[string]bool{}
			for _, group := range groups {
				for reader := range group {
					readers[reader] = true
				}
			}
			if len(readers) < 2 {
				readers = map[string]bool{}
			}
			for _, reader := range known {
				readers[reader] = true
			}
			result := []string{}
			for reader := range readers {
				result = append(result, reader)
			}
			sort.Strings(result)
			return result
		}
		byRoot, byPath := map[string][]string{}, map[string][]string{}
		all := map[string]bool{}
		for _, root := range agentSkillRoots(*agent) {
			byRoot[root] = collect(roots[canonicalSkillRoot(root)])
			for _, reader := range byRoot[root] {
				all[reader] = true
			}
		}
		for _, skill := range agent.Skills {
			rootReaders := map[string]bool{}
			for _, root := range agentSkillRoots(*agent) {
				if pathWithinLexical(skill.Path, root) {
					for _, reader := range byRoot[root] {
						rootReaders[reader] = true
					}
				}
			}
			byPath[skill.Path] = collect(skills[canonicalSkillRoot(skill.Path)], rootReaders)
			for _, reader := range byPath[skill.Path] {
				all[reader] = true
			}
		}
		agent.Capabilities["shared_skill_readers_by_root"] = byRoot
		agent.Capabilities["shared_skill_readers_by_path"] = byPath
		if len(all) > 0 {
			agent.Capabilities["shared_skills"] = true
			readers := []string{}
			for reader := range all {
				readers = append(readers, reader)
			}
			sort.Strings(readers)
			agent.Capabilities["shared_skill_readers"] = readers
		}
	}
}
