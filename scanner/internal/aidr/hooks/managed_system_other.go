//go:build !darwin && !linux

package hooks

func ApplySystemManaged(agent, action string) error { return code("aidr_managed_platform_unsupported") }
func SystemManagedConfigured(agent string) (bool, error) {
	return false, code("aidr_managed_platform_unsupported")
}
func SystemManagedVersion(agent string) (string, error) {
	return "", code("aidr_managed_platform_unsupported")
}
