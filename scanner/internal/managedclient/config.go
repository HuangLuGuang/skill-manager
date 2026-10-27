package managedclient

import (
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type CustomAgentConfig struct {
	AgentType  string `json:"agent_type"`
	Name       string `json:"name"`
	SkillsPath string `json:"skills_path"`
}

type SavedConnection struct {
	Server string `json:"server"`
	Token  string `json:"token"`
	Name   string `json:"name,omitempty"`
}

type Config struct {
	Server          string              `json:"server"`
	Token           string              `json:"token"`
	Name            string              `json:"name,omitempty"`
	Connections     []SavedConnection   `json:"connections,omitempty"`
	CustomAgents    []CustomAgentConfig `json:"custom_agents,omitempty"`
	AgentSkillRoots map[string][]string `json:"agent_skill_roots,omitempty"`
}

func normalizeConnection(connection SavedConnection) SavedConnection {
	connection.Server = strings.TrimRight(strings.TrimSpace(connection.Server), "/")
	connection.Token = strings.TrimSpace(connection.Token)
	connection.Name = strings.TrimSpace(connection.Name)
	return connection
}

func (config Config) FindConnection(server string) (SavedConnection, bool) {
	target := strings.TrimRight(strings.TrimSpace(server), "/")
	for _, connection := range config.Connections {
		connection = normalizeConnection(connection)
		if connection.Server == target && connection.Token != "" {
			return connection, true
		}
	}
	return SavedConnection{}, false
}

func (config *Config) syncActiveConnection() {
	active := normalizeConnection(SavedConnection{Server: config.Server, Token: config.Token, Name: config.Name})
	config.Server, config.Token, config.Name = active.Server, active.Token, active.Name
	connections := make([]SavedConnection, 0, len(config.Connections)+1)
	seen := map[string]bool{}
	if active.Server != "" && active.Token != "" {
		connections = append(connections, active)
		seen[active.Server] = true
	}
	for _, connection := range config.Connections {
		connection = normalizeConnection(connection)
		if connection.Server == "" || connection.Token == "" || seen[connection.Server] {
			continue
		}
		connections = append(connections, connection)
		seen[connection.Server] = true
	}
	config.Connections = connections
}

func LoadConfig(home string) (Config, error) {
	var config Config
	body, err := os.ReadFile(filepath.Join(home, ".agent-manager", "config.json"))
	if errors.Is(err, os.ErrNotExist) {
		return config, nil
	}
	if err != nil {
		return config, err
	}
	return ParseConfig(body)
}

// ParseConfig normalizes the same configuration whether read from disk or from
// an already validated private file.
func ParseConfig(body []byte) (Config, error) {
	var config Config
	err := json.Unmarshal(body, &config)
	if err == nil {
		config.syncActiveConnection()
	}
	return config, err
}

func SaveConfig(home string, config Config) error {
	config.syncActiveConnection()
	if config.Server == "" || config.Token == "" {
		return errors.New("server and token are required")
	}
	root := filepath.Join(home, ".agent-manager")
	if err := os.MkdirAll(root, 0o700); err != nil {
		return err
	}
	body, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return err
	}
	tmp := filepath.Join(root, "config.json.tmp")
	target := filepath.Join(root, "config.json")
	if err := os.WriteFile(tmp, body, 0o600); err != nil {
		return err
	}
	if err := os.Chmod(tmp, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, target)
}

func AddCustomAgent(home, name, skillsPath string) (CustomAgentConfig, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return CustomAgentConfig{}, errors.New("custom Agent name is required")
	}
	skillsPath = strings.TrimSpace(skillsPath)
	if skillsPath == "" {
		return CustomAgentConfig{}, errors.New("Skill directory is required")
	}
	absPath, err := filepath.Abs(skillsPath)
	if err != nil {
		return CustomAgentConfig{}, err
	}
	resolved, err := filepath.EvalSymlinks(absPath)
	if err != nil {
		return CustomAgentConfig{}, fmt.Errorf("Skill directory is unavailable: %w", err)
	}
	info, err := os.Stat(resolved)
	if err != nil || !info.IsDir() {
		return CustomAgentConfig{}, errors.New("Skill directory must be an existing directory")
	}
	config, err := LoadConfig(home)
	if err != nil {
		return CustomAgentConfig{}, err
	}
	for _, setting := range builtinAgentSettings(home, config) {
		for _, root := range setting.CurrentRoots {
			if canonicalSkillRoot(root) == filepath.Clean(resolved) {
				return CustomAgentConfig{}, fmt.Errorf("该 Skill 目录已由内置 Agent %s 管理，无需重复添加", setting.AgentType)
			}
		}
	}
	sum := sha256.Sum256([]byte(filepath.Clean(resolved)))
	item := CustomAgentConfig{
		AgentType:  fmt.Sprintf("custom-%x", sum[:6]),
		Name:       name,
		SkillsPath: filepath.Clean(resolved),
	}
	for index, existing := range config.CustomAgents {
		if filepath.Clean(existing.SkillsPath) == item.SkillsPath {
			item.AgentType = existing.AgentType
			config.CustomAgents[index] = item
			return item, SaveConfig(home, config)
		}
	}
	config.CustomAgents = append(config.CustomAgents, item)
	return item, SaveConfig(home, config)
}

func RemoveCustomAgent(home, agentType string) error {
	config, err := LoadConfig(home)
	if err != nil {
		return err
	}
	kept := config.CustomAgents[:0]
	for _, item := range config.CustomAgents {
		if item.AgentType != strings.TrimSpace(agentType) {
			kept = append(kept, item)
		}
	}
	if len(kept) == len(config.CustomAgents) {
		return errors.New("custom Agent not found")
	}
	config.CustomAgents = kept
	return SaveConfig(home, config)
}
