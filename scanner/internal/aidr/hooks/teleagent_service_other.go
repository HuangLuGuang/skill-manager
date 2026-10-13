//go:build !darwin

package hooks

func EnsureTeleAgentProxyService(home, executable string) error {
	if TeleAgentProxyRequired(home) {
		return code("aidr_plugin_host_unsupported")
	}
	return nil
}
