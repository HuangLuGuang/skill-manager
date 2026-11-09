package managedclient

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

type diagnosticContextKey struct{}
type diagnosticResponseBody struct {
	io.Reader
	io.Closer
}

type reportedDiagnosticError struct{ error }

func (e reportedDiagnosticError) Unwrap() error { return e.error }

func (api API) WithDiagnostics(store *Store) API {
	api.eventsStore = store
	return api
}
func (api API) do(request *http.Request) (*http.Response, error) {
	if api.eventsStore == nil {
		return api.http.Do(request)
	}
	random := make([]byte, 12)
	_, _ = rand.Read(random)
	id := hex.EncodeToString(random)
	request = request.Clone(request.Context())
	request.Header.Set("X-Request-ID", id)
	start := time.Now()
	response, err := api.http.Do(request)
	status := 0
	if response != nil {
		status = response.StatusCode
	}
	failure := err
	if failure == nil && response != nil && (status < 200 || status >= 300) {
		failure = fmt.Errorf("http_status_%d", status)
	}
	// Keep response error details bounded without consuming the caller's response body.
	fields := map[string]any{"request_id": id, "method": request.Method, "endpoint": request.URL.Path, "status_code": status, "duration_ms": time.Since(start).Milliseconds()}
	if response != nil && (status < 200 || status >= 300) {
		body, readErr := io.ReadAll(io.LimitReader(response.Body, 4096))
		response.Body = diagnosticResponseBody{io.MultiReader(bytes.NewReader(body), response.Body), response.Body}
		fields["response_detail"] = string(body)
		if readErr != nil {
			fields["response_read_error"] = readErr.Error()
		}
	}
	if values, ok := request.Context().Value(diagnosticContextKey{}).(map[string]any); ok {
		for key, value := range values {
			fields[key] = value
		}
	}
	fields["timeout_ms"] = api.http.Timeout.Milliseconds()
	if deadline, ok := request.Context().Deadline(); ok {
		fields["deadline_remaining_ms"] = deadline.Sub(start).Milliseconds()
	}
	if response != nil {
		fields["server_request_id"] = response.Header.Get("X-Request-ID")
	}
	if request.Context().Err() != nil {
		fields["context_error"] = request.Context().Err().Error()
	}
	if !errors.Is(request.Context().Err(), context.Canceled) {
		logSyncTransition(api.eventsStore, "http:"+request.Method+":"+request.URL.Path, failure, fields)
	}
	if err != nil {
		return response, reportedDiagnosticError{err}
	}
	return response, err
}

func (api API) responseError(response *http.Response, detail string) error {
	err := fmt.Errorf("Agent Manager 返回 %s: %s", response.Status, detail)
	if api.eventsStore != nil {
		return reportedDiagnosticError{err}
	}
	return err
}
