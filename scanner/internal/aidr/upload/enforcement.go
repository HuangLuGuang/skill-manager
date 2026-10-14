package upload

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"

	"skill-manager/scanner/internal/aidr/enforcement"
)

func (c *Client) RuntimeGet(ctx context.Context, resource string) (body []byte, result Result) {
	if resource != "snapshot" && resource != "commands" && resource != "bootstrap" && resource != "collection/device" {
		return nil, Result{Code: "aidr_enforcement_request_invalid"}
	}
	diagnostic := HTTPDiagnostic{Method: http.MethodGet, Resource: "enforcement/" + resource}
	defer func() { c.reportHTTP(ctx, diagnostic, result) }()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/api/v1/clients/"+url.PathEscape(c.clientID)+"/aidr/enforcement/"+resource, nil)
	if err != nil {
		return nil, Result{Code: "aidr_enforcement_request_invalid"}
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Accept-Encoding", "identity")
	response, err := c.http.Do(req)
	if err != nil {
		return nil, Result{Code: "aidr_upload_transport", Retryable: true}
	}
	defer response.Body.Close()
	diagnostic.StatusCode = response.StatusCode
	data, err := io.ReadAll(io.LimitReader(response.Body, 1048577))
	if err != nil || len(data) > 1048576 {
		return nil, Result{Code: "aidr_upload_response_invalid", Retryable: true}
	}
	diagnostic.ServerCode = responseErrorCode(data)
	if response.StatusCode == 401 || response.StatusCode == 403 {
		return nil, Result{Code: "aidr_upload_auth_rejected"}
	}
	if resource == "bootstrap" && response.StatusCode != 200 {
		var problem struct {
			ErrorCode string `json:"error_code"`
			Detail    struct {
				ErrorCode string `json:"error_code"`
			} `json:"detail"`
		}
		_ = json.Unmarshal(data, &problem)
		code := problem.ErrorCode
		if code == "" {
			code = problem.Detail.ErrorCode
		}
		switch code {
		case "aidr.system_collection_disabled", "aidr.system_policy_required", "aidr.enforcement_signer_unavailable":
			return nil, Result{Code: code}
		}
	}
	if retryableHTTPStatus(response.StatusCode) {
		return nil, Result{Code: "aidr_upload_server_unavailable", Retryable: true}
	}
	if response.StatusCode != 200 {
		return nil, Result{Code: "aidr_upload_request_rejected"}
	}
	return data, Result{}
}

// SystemCollection posts only discovery or target selections, never device-authored policies.
func (c *Client) SystemCollection(ctx context.Context, resource string, body any) ([]byte, Result) {
	if resource != "discovery" && resource != "selection" {
		return nil, Result{Code: "aidr_enforcement_request_invalid"}
	}
	raw, err := json.Marshal(body)
	if err != nil || len(raw) > 65536 {
		return nil, Result{Code: "aidr_enforcement_request_invalid"}
	}
	return c.post(ctx, "enforcement/collection/"+resource, raw, nil)
}

func (c *Client) SendRuntime(ctx context.Context, s *enforcement.Store) (Result, error) {
	if err := c.Bind(ctx, s.Guard); err != nil {
		return Result{}, err
	}
	b, err := s.Prepare(ctx)
	if err != nil || b == nil {
		return Result{}, err
	}
	data, result := c.post(ctx, "enforcement/records", b.Payload, nil)
	if result.Code != "" {
		return result, nil
	}
	var ack struct {
		Schema  int    `json:"schema_version"`
		Device  string `json:"client_id"`
		Durable bool   `json:"durable"`
		Count   int    `json:"accepted"`
		Digest  string `json:"digest"`
	}
	if decode(data, &ack) != nil || ack.Schema != 1 || ack.Device != c.clientID || !ack.Durable || ack.Count != b.Count || ack.Digest != b.Digest {
		return Result{Code: "aidr_enforcement_ack_invalid", Retryable: true}, nil
	}
	if err = s.Acknowledge(ctx, ack.Digest, ack.Count); err != nil {
		return Result{}, err
	}
	return Result{Uploaded: true}, nil
}

func DecodeRuntimeSnapshot(data []byte) ([]byte, error) {
	var value struct {
		Envelope *enforcement.Envelope `json:"envelope"`
	}
	if decode(data, &value) != nil {
		return nil, errors.New("aidr_enforcement_snapshot_invalid")
	}
	if value.Envelope == nil {
		return nil, nil
	}
	return json.Marshal(value.Envelope)
}
func DecodeRuntimeCommands(data []byte) ([]json.RawMessage, error) {
	var value struct {
		Items []enforcement.Envelope `json:"items"`
	}
	if decode(data, &value) != nil || len(value.Items) > 16 {
		return nil, errors.New("aidr_enforcement_commands_invalid")
	}
	var result []json.RawMessage
	for _, item := range value.Items {
		raw, _ := json.Marshal(item)
		result = append(result, raw)
	}
	return result, nil
}
