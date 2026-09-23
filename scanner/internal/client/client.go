package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"skill-manager/scanner/internal/localize"
)

type Client struct {
	server     string
	token      string
	httpClient *http.Client
}

type HTTPStatusError struct {
	Operation  string
	Status     string
	StatusCode int
	Body       string
}

func (e *HTTPStatusError) Error() string {
	return fmt.Sprintf("%s failed: %s: %s", e.Operation, e.Status, e.Body)
}

func IsNotFound(err error) bool {
	var statusError *HTTPStatusError
	return errors.As(err, &statusError) && statusError.StatusCode == http.StatusNotFound
}

// IsSubmissionNotOwned distinguishes a stale submission reference from other
// authorization failures. A client can retain a version ID after switching
// Agent Manager addresses or Scanner Tokens, but the new token must not be
// allowed to read a submission created by another token.
func IsSubmissionNotOwned(err error) bool {
	var statusError *HTTPStatusError
	if !errors.As(err, &statusError) || statusError.StatusCode != http.StatusForbidden {
		return false
	}
	var payload struct {
		Detail    string `json:"detail"`
		ErrorCode string `json:"error_code"`
	}
	if json.Unmarshal([]byte(statusError.Body), &payload) == nil {
		if payload.ErrorCode == "scanner.submission_not_owned" {
			return true
		}
		return strings.Contains(strings.ToLower(payload.Detail), "only read own submissions")
	}
	return strings.Contains(strings.ToLower(statusError.Body), "only read own submissions")
}

type SubmitOptions struct {
	UseBehavioral   bool
	UseSkillspector bool
	UseSandbox      bool
	UseLLM          bool
	JudgementMode   string
	ManifestJSON    string
	ScannerVersion  string
	HostID          string
}

type SubmitResult struct {
	AlreadySubmitted      bool              `json:"already_submitted,omitempty"`
	ScanProgressStage     string            `json:"scan_progress_stage,omitempty"`
	ScanProgressAnalyzers map[string]string `json:"scan_progress_analyzers,omitempty"`
	SkillID               string            `json:"skill_id,omitempty"`
	VersionID             string            `json:"version_id,omitempty"`
	VersionNo             int               `json:"version_no,omitempty"`
	SourceVersion         string            `json:"source_version,omitempty"`
	Name                  string            `json:"name,omitempty"`
	Status                string            `json:"status,omitempty"`
	RiskLevel             string            `json:"risk_level,omitempty"`
	FindingsCount         int               `json:"findings_count,omitempty"`
	Message               string            `json:"message,omitempty"`
	DetailURL             string            `json:"detail_url,omitempty"`
}

type importResult struct {
	ScanProgressStage     string            `json:"scan_progress_stage"`
	ScanProgressAnalyzers map[string]string `json:"scan_progress_analyzers"`
	SkillID               string            `json:"skill_id"`
	VersionID             string            `json:"version_id"`
	VersionNo             int               `json:"version_no"`
	SourceVersion         string            `json:"source_version"`
	Name                  string            `json:"name"`
	Status                string            `json:"status"`
	RiskLevel             string            `json:"risk_level"`
	Vetting               *struct {
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
	_ = writer.WriteField("use_skillspector", boolString(opts.UseSkillspector))
	_ = writer.WriteField("use_deep_scan", boolString(opts.UseSkillspector))
	_ = writer.WriteField("use_sandbox", boolString(opts.UseSandbox))
	_ = writer.WriteField("use_llm", boolString(opts.UseLLM))
	if opts.JudgementMode != "" {
		_ = writer.WriteField("judgement_mode", opts.JudgementMode)
	}
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
		return result, &HTTPStatusError{
			Operation:  "read result",
			Status:     response.Status,
			StatusCode: response.StatusCode,
			Body:       strings.TrimSpace(string(payload)),
		}
	}
	var payload importResult
	if err := json.NewDecoder(response.Body).Decode(&payload); err != nil {
		return result, err
	}
	result = SubmitResult{
		ScanProgressStage:     payload.ScanProgressStage,
		ScanProgressAnalyzers: payload.ScanProgressAnalyzers,
		SkillID:               payload.SkillID,
		VersionID:             payload.VersionID,
		VersionNo:             payload.VersionNo,
		SourceVersion:         payload.SourceVersion,
		Name:                  payload.Name,
		Status:                payload.Status,
		RiskLevel:             payload.RiskLevel,
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
	request.Header.Set("Accept-Language", scannerLocale())
	if strings.TrimSpace(c.token) != "" {
		request.Header.Set("Authorization", "Bearer "+strings.TrimSpace(c.token))
	}
}

func scannerLocale() string {
	return localize.Locale()
}

func boolString(value bool) string {
	if value {
		return "true"
	}
	return "false"
}
