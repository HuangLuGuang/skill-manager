package main

import (
	"fmt"

	"skill-manager/scanner/internal/aidr/upload"
	"skill-manager/scanner/internal/managedclient"
)

func aidrHTTPObserver(home string) func(upload.HTTPDiagnostic) {
	if home == "" {
		return nil
	}
	return func(d upload.HTTPDiagnostic) {
		var failure error
		if d.Code != "" {
			if d.Error != "" {
				failure = fmt.Errorf("%s", d.Error)
			} else if d.StatusCode != 0 {
				failure = fmt.Errorf("%s: HTTP %d %s", d.Code, d.StatusCode, d.ServerCode)
			} else {
				failure = fmt.Errorf("%s", d.Code)
			}
		}
		fields := map[string]any{
			"method": d.Method, "resource": d.Resource, "status_code": d.StatusCode,
			"error_code": d.Code, "server_error_code": d.ServerCode, "retryable": d.Retryable,
			"request_id": d.RequestID, "server_request_id": d.ServerRequestID, "duration_ms": d.DurationMS, "timeout_ms": d.TimeoutMS,
		}
		if d.ContextError != "" {
			fields["context_error"] = d.ContextError
		}
		if d.HasDeadline {
			fields["deadline_remaining_ms"] = d.DeadlineRemainingMS
		}
		managedclient.RecordBackgroundSyncDiagnostic(home, "aidr_http:"+d.Method+":"+d.Resource, failure, fields)
	}
}
