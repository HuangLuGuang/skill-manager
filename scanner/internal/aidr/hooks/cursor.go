package hooks

import products "skill-manager/scanner/internal/aidr/catalog"

func IsPreTool(agent, event string) bool { return products.Kind(agent, event) == "tool.pre" }
