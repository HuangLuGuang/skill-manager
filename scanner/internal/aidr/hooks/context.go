package hooks

import (
	"encoding/json"
	"skill-manager/scanner/internal/aidr/agentlog"
)

// HostContext contains only metadata explicitly supplied with this Hook event.
type HostContext struct {
	Model          string   `json:"model,omitempty"`
	Cwd            string   `json:"cwd,omitempty"`
	WorkspaceRoots []string `json:"workspace_roots,omitempty"`
	Redacted       bool     `json:"redacted"`
	Truncated      bool     `json:"truncated"`
}

func projectHostContext(in input, policy agentlog.AuditPolicy) *HostContext {
	c := &HostContext{}
	project := func(value string, limit int) string {
		text, redacted, truncated := agentlog.ProjectMetadataText(value, limit, policy)
		c.Redacted = c.Redacted || redacted
		c.Truncated = c.Truncated || truncated
		return text
	}
	var model string
	_ = json.Unmarshal(in.Model, &model)
	roots := in.WorkspaceRoots
	if len(roots) > 8 {
		roots = roots[:8]
		c.Truncated = true
	}
	for _, root := range roots {
		if value := project(root, 512); value != "" {
			c.WorkspaceRoots = append(c.WorkspaceRoots, value)
		}
	}

	c.Model, c.Cwd = project(model, 256), project(in.Cwd, 512)
	if c.Model == "" && c.Cwd == "" && len(c.WorkspaceRoots) == 0 {
		return nil
	}
	return c
}
