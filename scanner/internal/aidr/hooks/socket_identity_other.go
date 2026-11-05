//go:build !darwin && !linux && !windows

package hooks

func (r *Receiver) SocketIdentity() (map[string]string, error) {
	return nil, code("aidr_hook_platform_unsupported")
}
