package upload

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestBootstrapPreservesActionablePlatformErrorsWithoutLeakingDetails(t *testing.T) {
	for _, test := range []struct {
		status     int
		code, want string
	}{
		{409, "aidr.system_policy_required", "aidr.system_policy_required"},
		{409, "aidr.system_collection_disabled", "aidr.system_collection_disabled"},
		{503, "aidr.enforcement_signer_unavailable", "aidr.enforcement_signer_unavailable"},
		{500, "private-server-details", "aidr_upload_server_unavailable"},
		{403, "aidr.system_collection_disabled", "aidr_upload_auth_rejected"},
	} {
		t.Run(test.code+fmt.Sprint(test.status), func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") == "" || r.URL.Path != "/api/v1/clients/device-one/aidr/enforcement/bootstrap" {
					t.Error("device auth or route lost")
				}
				w.WriteHeader(test.status)
				fmt.Fprintf(w, `{"error_code":%q,"detail":"private-server-details"}`, test.code)
			}))
			defer server.Close()
			c := newClient(t, server.URL)
			body, result := c.RuntimeGet(context.Background(), "bootstrap")
			if body != nil || result.Code != test.want {
				t.Fatal(result, string(body))
			}
		})
	}
}
