package platformtls

import (
	"crypto/tls"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestPlatformConnectionsAcceptSelfSignedCertificates(t *testing.T) {
	other := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) }))
	defer other.Close()
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/redirect" {
			http.Redirect(w, r, other.URL, 302)
			return
		}
		w.WriteHeader(200)
	}))
	defer server.Close()
	base := http.DefaultTransport.(*http.Transport).Clone()
	base.MaxConnsPerHost = 1
	base.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12}
	transport := New(base)
	client := &http.Client{Transport: transport}
	defer client.CloseIdleConnections()
	for _, target := range []string{server.URL, other.URL, server.URL + "/redirect"} {
		response, err := client.Get(target)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != 200 {
			t.Fatalf("status=%d", response.StatusCode)
		}
	}
	if base.TLSClientConfig.InsecureSkipVerify {
		t.Fatal("base transport mutated")
	}
	if transport.MaxConnsPerHost != 1 || transport.TLSClientConfig.MinVersion != tls.VersionTLS12 {
		t.Fatal("transport limits were lost")
	}
}
