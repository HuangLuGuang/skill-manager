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
			failure = fmt.Errorf("%s: HTTP %d %s", d.Code, d.StatusCode, d.ServerCode)
		}
		managedclient.RecordBackgroundSyncDiagnostic(home, "aidr_http:"+d.Method+":"+d.Resource, failure, map[string]any{
			"method": d.Method, "resource": d.Resource, "status_code": d.StatusCode,
			"error_code": d.Code, "server_error_code": d.ServerCode, "retryable": d.Retryable,
		})
	}
}
