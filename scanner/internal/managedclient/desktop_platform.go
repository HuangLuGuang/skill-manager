package managedclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"
)

type DesktopRequest struct {
	Version        int               `json:"version"`
	Method         string            `json:"method"`
	Recovery       bool              `json:"recovery,omitempty"`
	Filters        map[string]string `json:"filters,omitempty"`
	LocalAgentID   string            `json:"local_agent_id,omitempty"`
	AgentType      string            `json:"agent_type,omitempty"`
	ManagedAgentID string            `json:"managed_agent_id,omitempty"`
	ManualModel    map[string]string `json:"manual_model,omitempty"`
}

// DesktopPlatform owns the platform HTTP contract; callers cannot supply URLs or credentials.
func DesktopPlatform(ctx context.Context, home string, request DesktopRequest) (json.RawMessage, error) {
	var suffix, code, method string
	timeout := 15 * time.Second
	switch request.Method {
	case "platform-status":
		suffix, code, method, timeout = "/status", "client_status", http.MethodGet, 10*time.Second
	case "platform-history":
		suffix, code, method = "/history", "client_history", http.MethodGet
	case "model-catalog":
		suffix, code, method, timeout = "/model-catalog/refresh", "model_catalog_refresh", http.MethodPost, 30*time.Second
	case "manual-model-options":
		suffix, code, method, timeout = "/manual-model/options", "manual_model", http.MethodPost, 30*time.Second
	case "manual-model-credential":
		suffix, code, method, timeout = "/manual-model/credential", "manual_model", http.MethodPost, 30*time.Second
	default:
		return nil, fmt.Errorf("client_ipc_invalid_request")
	}
	config, err := LoadConfig(home)
	if err != nil || config.Server == "" || config.Token == "" {
		return nil, fmt.Errorf("client_not_configured")
	}
	snapshot, err := DesktopSnapshot(ctx, home)
	if err != nil {
		return nil, err
	}
	id := snapshot["inventory"].(Inventory).ClientID
	path := "/api/v1/clients/" + url.PathEscape(id) + suffix
	query := url.Values{}
	for key, value := range request.Filters {
		query.Set(key, value)
	}
	if request.Method == "platform-history" && len(query) > 0 {
		path += "?" + query.Encode()
	}
	var body io.Reader
	if method == http.MethodPost {
		payload := map[string]string{"local_agent_id": request.LocalAgentID, "agent_type": request.AgentType, "managed_agent_id": request.ManagedAgentID}
		if request.Method == "manual-model-credential" {
			payload = request.ManualModel
		}
		data, _ := json.Marshal(payload)
		body = bytes.NewReader(data)
	}
	api := NewAPI(config.Server, config.Token, timeout)
	req, err := api.request(ctx, method, path, body)
	if err != nil {
		return nil, fmt.Errorf("%s_unavailable", code)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	response, err := api.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%s_unavailable", code)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		detail, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return nil, fmt.Errorf("%s_http_%d: %s", code, response.StatusCode, detail)
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, 16*1024*1024+1))
	if err != nil || len(data) > 16*1024*1024 || !json.Valid(data) {
		return nil, fmt.Errorf("%s_invalid_response", code)
	}
	return data, nil
}
