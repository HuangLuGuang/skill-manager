// Package platformtls provides the transport for client-to-platform connections.
package platformtls

import (
	"crypto/tls"
	"net/http"
)

func New(base *http.Transport) *http.Transport {
	transport := base.Clone()
	if transport.TLSClientConfig == nil {
		transport.TLSClientConfig = &tls.Config{}
	}
	// Platform connections accept self-signed certificates without verifying server identity.
	transport.TLSClientConfig.InsecureSkipVerify = true
	return transport
}
