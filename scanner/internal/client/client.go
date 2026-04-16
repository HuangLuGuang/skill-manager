package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Client struct {
	server     string
	token      string
	httpClient *http.Client
}

type SubmitOptions struct {
	UseBehavioral  bool
	UseSandbox     bool
	UseLLM         bool
	ManifestJSON   string
	ScannerVersion string
	HostID         string
}

type SubmitResult struct {
	SkillID       string `json:"skill_id,omitempty"`
	Name          string `json:"name,omitempty"`
	Status        string `json:"status,omitempty"`
	RiskLevel     string `json:"risk_level,omitempty"`
	FindingsCount int    `json:"findings_count,omitempty"`
	Message       string `json:"message,omitempty"`
	DetailURL     string `json:"detail_url,omitempty"`
}

type importResult struct {
	SkillID   string `json:"skill_id"`
	Name      string `json:"name"`
	Status    string `json:"status"`
	RiskLevel string `json:"risk_level"`
	Vetting   *struct {
		FindingsCount int `json:"findings_count"`
	} `json:"vetting"`
}

func New(server string, token string, timeout time.Duration) Client {
	return Client{
		server: strings.TrimRight(server, "/"),
		token:  token,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

func (c Client) SubmitZip(ctx context.Context, zipPath string, opts SubmitOptions) (SubmitResult, error) {
	var result SubmitResult
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	fileWriter, err := writer.CreateFormFile("file", filepath.Base(zipPath))
	if err != nil {
		return result, err
	}
	file, err := os.Open(zipPath)
	if err != nil {
		return result, err
	}
	if _, err := io.Copy(fileWriter, file); err != nil {
		file.Close()
		return result, err
	}
	if err := file.Close(); err != nil {
		return result, err
	}
	if opts.ManifestJSON != "" {
		if err := writer.WriteField("manifest", opts.ManifestJSON); err != nil {
			return result, err
		}
	}
	if opts.ScannerVersion != "" {
		if err := writer.WriteField("scanner_version", opts.ScannerVersion); err != nil {
			return result, err
		}
	}
	if opts.HostID != "" {
		if err := writer.WriteField("host_id", opts.HostID); err != nil {
			return result, err
		}
	}
	_ = writer.WriteField("use_behavioral", boolString(opts.UseBehavioral))
	_ = writer.WriteField("use_sandbox", boolString(opts.UseSandbox))
	_ = writer.WriteField("use_llm", boolString(opts.UseLLM))
	if err := writer.Close(); err != nil {
		return result, err
	}

	endpoint := c.server + "/api/v1/scanner/imports"
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, &body)
	if err != nil {
		return result, err
	}
	request.Header.Set("Content-Type", writer.FormDataContentType())
	c.authorize(request)

	response, err := c.httpClient.Do(request)
	if err != nil {
		return result, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		payload, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return result, fmt.Errorf("submit failed: %s: %s", response.Status, strings.TrimSpace(string(payload)))
	}
	if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
		return result, err
	}
	if result.SkillID != "" {
		result.DetailURL = c.server + "/skills/" + result.SkillID
	}
	return result, nil
}

func (c Client) GetImport(ctx context.Context, skillID string) (SubmitResult, error) {
	var result SubmitResult
	if strings.TrimSpace(skillID) == "" {
		return result, fmt.Errorf("skill_id is required")
	}
	endpoint := c.server + "/api/v1/scanner/imports/" + skillID
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return result, err
	}
	c.authorize(request)

	response, err := c.httpClient.Do(request)
	if err != nil {
		return result, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		payload, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return result, fmt.Errorf("read result failed: %s: %s", response.Status, strings.TrimSpace(string(payload)))
	}
	var payload importResult
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		return result, err
	}
	result = SubmitResult{
		SkillID:   payload.SkillID,
		Name:      payload.Name,
		Status:    payload.Status,
		RiskLevel: payload.RiskLevel,
	}
	if payload.Vetting != nil {
		result.FindingsCount = payload.Vetting.FindingsCount
	}
	if result.SkillID != "" {
		result.DetailURL = c.server + "/skills/" + result.SkillID
	}
	return result, nil
}

func (c Client) authorize(request *http.Request) {
	if strings.TrimSpace(c.token) != "" {
		request.Header.Set("Authorization", "Bearer "+strings.TrimSpace(c.token))
	}
}

func boolString(value bool) string {
	if value {
		return "true"
	}
	return "false"
}
