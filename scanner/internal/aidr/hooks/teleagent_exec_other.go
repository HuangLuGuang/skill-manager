//go:build !darwin

package hooks

import (
	"net"
	"skill-manager/scanner/internal/runtimeinfo"
)

func proxyListener(address string) (net.Listener, error) { return net.Listen("tcp", address) }
func checkProxyCandidate(home, binary string) (runtimeinfo.Info, error) {
	return runtimeinfo.Info{}, code("aidr_plugin_host_unsupported")
}
func execProxyCandidate(home string, c proxyCandidate, l net.Listener) error {
	return code("aidr_plugin_host_unsupported")
}
