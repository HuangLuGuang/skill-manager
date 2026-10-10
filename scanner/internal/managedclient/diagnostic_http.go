package managedclient

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/http"
	"time"
)

type diagnosticContextKey struct{}

type diagnosticTransport struct {
	base  http.RoundTripper
	store *Store
}

func (api API) WithDiagnostics(store *Store) API {
	api.eventsStore = store
	copy := *api.http
	base := copy.Transport
	if base == nil {
		base = http.DefaultTransport
	}
	if _, ok := base.(*diagnosticTransport); ok {
		return api
	}
	copy.Transport = &diagnosticTransport{base: base, store: store}
	api.http = &copy
	return api
}
func (transport *diagnosticTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	bytes := make([]byte, 12)
	_, _ = rand.Read(bytes)
	id := hex.EncodeToString(bytes)
	request = request.Clone(request.Context())
	request.Header.Set("X-Request-ID", id)
	start := time.Now()
	response, err := transport.base.RoundTrip(request)
	status := 0
	if response != nil {
		status = response.StatusCode
	}
	failure := err
	if failure == nil && status >= 400 {
		failure = fmt.Errorf("http_status_%d", status)
	}
	// Query strings and request/response bodies may contain credentials or Skill data.
	fields := map[string]any{"request_id": id, "method": request.Method, "endpoint": request.URL.Path, "status_code": status, "duration_ms": time.Since(start).Milliseconds()}
	if values, ok := request.Context().Value(diagnosticContextKey{}).(map[string]any); ok {
		for key, value := range values {
			fields[key] = value
		}
	}
	logSyncTransition(transport.store, "http:"+request.Method+":"+request.URL.Path, failure, fields)
	return response, err
}
