// Package upload sends the frozen local outbox with bounded HTTP exchanges.
package upload

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"skill-manager/scanner/internal/aidr/agentlog"
	"skill-manager/scanner/internal/aidr/localstore"
)

type Options struct {
	Server, ClientID, Token string
}
type Client struct {
	base, clientID, token string
	http                  *http.Client
	policySupported       bool
	policyCode            string
	policyRefreshed       string
	hookUploadCode        string
	hookNextUpload        time.Time
}
type Capability struct {
	ParserStatus  string `json:"parser_status,omitempty"`
	ParserVersion string `json:"parser_version,omitempty"`
	Agent         string `json:"agent"`
	Version       string `json:"version"`
	Status        string `json:"status"`
}
type Discovery struct {
	SourceID string                        `json:"source_id,omitempty"`
	Progress *localstore.DiscoveryProgress `json:"progress,omitempty"`
	Agent    string                        `json:"agent"`
	Status   string                        `json:"status"`
	Reasons  []string                      `json:"reason_codes"`
}
type Result struct {
	Uploaded  bool
	Code      string
	Retryable bool
}

func New(o Options) (*Client, error) {
	u, err := url.Parse(o.Server)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || !regexp.MustCompile(`^[A-Za-z0-9_.-]{1,128}$`).MatchString(o.ClientID) || strings.TrimSpace(o.Token) == "" || strings.ContainsAny(o.Token, "\r\n") {
		return nil, errors.New("aidr_upload_config_invalid")
	}
	loopback := u.Hostname() == "localhost"
	if ip := net.ParseIP(u.Hostname()); ip != nil {
		loopback = ip.IsLoopback()
	}
	if u.Scheme != "https" && !(u.Scheme == "http" && loopback) {
		return nil, errors.New("aidr_upload_https_required")
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.DisableCompression = true
	transport.MaxIdleConnsPerHost = 1
	transport.MaxConnsPerHost = 1
	return &Client{base: strings.TrimRight(u.String(), "/"), clientID: o.ClientID, token: o.Token, http: &http.Client{Timeout: 10 * time.Second, Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}
func (c *Client) Close() { c.http.CloseIdleConnections() }
func (c *Client) Bind(ctx context.Context, s *localstore.Store) error {
	identity := fmt.Sprintf("%s\n%s", c.base, c.clientID)
	err := s.BindDestination(ctx, identity)
	if !errors.Is(err, localstore.ErrLegacyDestination) {
		return err
	}
	data, result := c.post(ctx, "state-migration", []byte("{}"), nil)
	if result.Code != "" {
		return errors.New(result.Code)
	}
	var proof struct {
		Schema int     `json:"schema_version"`
		Client string  `json:"client_id"`
		Suffix *string `json:"legacy_suffix"`
	}
	if decode(data, &proof) != nil || proof.Schema != 2 || proof.Client != c.clientID || proof.Suffix == nil || !regexp.MustCompile(`^[1-9][0-9]{0,18}$`).MatchString(*proof.Suffix) {
		return errors.New("aidr_upload_destination_migration_unavailable")
	}
	return s.BindDestinationWithLegacy(ctx, identity, identity+"\n"+*proof.Suffix)
}
func (c *Client) post(ctx context.Context, path string, raw []byte, headers map[string]string) ([]byte, Result) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/api/v1/clients/"+url.PathEscape(c.clientID)+"/aidr/"+path, bytes.NewReader(raw))
	if err != nil {
		return nil, Result{Code: "aidr_upload_request_invalid"}
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept-Encoding", "identity")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	response, err := c.http.Do(req)
	if err != nil {
		return nil, Result{Code: "aidr_upload_transport", Retryable: true}
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, 65537))
	if err != nil || len(data) > 65536 {
		return nil, Result{Code: "aidr_upload_response_invalid", Retryable: true}
	}
	if response.StatusCode == 401 || response.StatusCode == 403 {
		// A device reporting pause is a reversible upload condition, not an
		// invalid credential. Keep collecting locally and retry the frozen bytes.
		var problem struct {
			Code string `json:"error_code"`
		}
		if response.StatusCode == 403 && json.Unmarshal(data, &problem) == nil && problem.Code == "aidr.reporting_disabled" {
			return nil, Result{Code: "aidr_upload_reporting_paused", Retryable: true}
		}
		return nil, Result{Code: "aidr_upload_auth_rejected"}
	}
	if response.StatusCode == 429 || response.StatusCode >= 500 {
		return nil, Result{Code: "aidr_upload_server_unavailable", Retryable: true}
	}
	if response.StatusCode != 200 {
		return nil, Result{Code: "aidr_upload_request_rejected"}
	}
	return data, Result{}
}
func decode(data []byte, value any) error {
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(value); err != nil {
		return err
	}
	var trailing any
	if err := d.Decode(&trailing); err != io.EOF {
		return errors.New("aidr_upload_response_invalid")
	}
	return nil
}
func (c *Client) SendOne(ctx context.Context, s *localstore.Store) (result Result, err error) {
	if err = c.Bind(ctx, s); err != nil {
		return result, err
	}
	stream, err := s.StreamID(ctx)
	if err != nil {
		return result, err
	}
	b, err := s.Prepare(ctx, 500, 1<<20)
	if err != nil || b == nil {
		return result, err
	}
	data, result := c.post(ctx, "events:batch", b.Payload, map[string]string{"Idempotency-Key": b.ID, "X-AIDR-Stream-ID": stream})
	if result.Code == "" {
		var ack struct {
			Schema   int    `json:"schema_version"`
			Client   string `json:"client_id"`
			Stream   string `json:"stream_id"`
			ID       string `json:"batch_id"`
			Digest   string `json:"digest"`
			Accepted int    `json:"accepted"`
			Durable  bool   `json:"durable"`
		}
		var envelope localstore.Envelope
		if decode(data, &ack) != nil || json.Unmarshal(b.Payload, &envelope) != nil || ack.Schema != 2 || ack.Client != c.clientID || ack.Stream != stream || ack.ID != b.ID || ack.Digest != b.Digest || ack.Accepted != len(envelope.Records) || !ack.Durable {
			result = Result{Code: "aidr_upload_ack_invalid", Retryable: true}
		} else {
			if err = s.Acknowledge(ctx, b.ID, b.Digest); err != nil {
				return result, err
			}
			result.Uploaded = true
		}
	}
	// The queue was already committed; an error recording upload health must
	// never roll it forward or convert a rejected receipt into an ACK.
	if e := s.SetUploadCode(ctx, result.Code); e != nil {
		return result, e
	}
	return result, nil
}

func (c *Client) Heartbeat(ctx context.Context, s *localstore.Store, capabilities []Capability, discovery []Discovery) (Result, error) {
	if err := c.Bind(ctx, s); err != nil {
		return Result{}, err
	}
	stream, err := s.StreamID(ctx)
	if err != nil {
		return Result{}, err
	}
	status, err := s.Status(ctx)
	if err != nil {
		return Result{}, err
	}
	code := status.IntakeCode
	if code == "" {
		code = status.CapacityCode
	}
	payload := struct {
		Stream       string        `json:"stream_id"`
		Capabilities []Capability  `json:"capabilities"`
		Queued       int           `json:"queued_records"`
		Events       int           `json:"logical_events"`
		Evicted      int           `json:"evicted_event_payloads"`
		Intake       string        `json:"intake_code"`
		Recovery     string        `json:"recovery_code"`
		Upload       string        `json:"upload_code"`
		Discovery    []Discovery   `json:"discovery"`
		Policy       *PolicyHealth `json:"audit_policy,omitempty"`
	}{stream, capabilities, status.Queued, status.LogicalEvents, status.EvictedPayloads, code, status.RecoveryCode, status.UploadCode, discovery, nil}
	if c.policySupported {
		payload.Policy = &PolicyHealth{Policy: s.Policy(), Code: c.policyCode, RefreshedAt: c.policyRefreshed}
	}
	if payload.Capabilities == nil {
		payload.Capabilities = []Capability{}
	}
	if payload.Discovery == nil {
		payload.Discovery = []Discovery{}
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return Result{}, err
	}
	data, result := c.post(ctx, "heartbeat", raw, nil)
	if result.Code != "" {
		return result, nil
	}
	var ack struct {
		Schema   int    `json:"schema_version"`
		Client   string `json:"client_id"`
		Stream   string `json:"stream_id"`
		Received string `json:"server_received_at"`
	}
	if decode(data, &ack) != nil || ack.Schema != 2 || ack.Client != c.clientID || ack.Stream != stream {
		return Result{Code: "aidr_upload_ack_invalid", Retryable: true}, nil
	}
	return result, nil
}

func RetryDelay(attempt int) time.Duration {
	if attempt < 0 {
		attempt = 0
	}
	if attempt > 6 {
		attempt = 6
	}
	delay := time.Second * time.Duration(1<<attempt)
	if delay > time.Minute {
		return time.Minute
	}
	return delay
}

type PolicyHealth struct {
	Policy      *agentlog.AuditPolicy `json:"policy"`
	Code        string                `json:"code"`
	RefreshedAt string                `json:"refreshed_at"`
}

func (c *Client) RefreshPolicy(ctx context.Context, s *localstore.Store) error {
	stream, err := s.StreamID(ctx)
	if err != nil {
		return err
	}
	n, err := s.LastSequence(ctx)
	if err != nil {
		return err
	}
	after, err := s.PolicyAppliedAfter(ctx)
	if err != nil {
		return err
	}
	raw, _ := json.Marshal(map[string]string{"stream_id": stream, "last_sequence": fmt.Sprint(n), "applied_receipt": s.Policy().Receipt, "applied_after": after})
	data, result := c.post(ctx, "audit-policy", raw, map[string]string{"X-AIDR-Policy-Schema": "2", "X-AIDR-Audit-Lifecycle": "1", "X-AIDR-Message-Capture": "1", "X-AIDR-Content-Options": "1"})
	if result.Code != "" {
		c.policyCode = "aidr_policy_cached"
		return nil
	}
	var p agentlog.AuditPolicy
	if decode(data, &p) != nil || !p.Valid() || p.Version == "0" {
		c.policyCode = "aidr_policy_response_invalid"
		return nil
	}
	if err = s.SavePolicy(ctx, p); err != nil {
		return err
	}
	c.policySupported = true
	c.policyCode = "aidr_policy_applied"
	c.policyRefreshed = time.Now().UTC().Format(time.RFC3339)
	return nil
}
