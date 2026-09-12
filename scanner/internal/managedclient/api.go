package managedclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type API struct {
	server string
	token  string
	http   *http.Client
}

type AgentCredential struct {
	Token              string   `json:"token"`
	TokenPrefix        string   `json:"token_prefix"`
	BoundAgentID       string   `json:"bound_agent_id"`
	AllowedModels      []string `json:"allowed_models"`
	AllowedMCPGateways []string `json:"allowed_mcp_gateways"`
}

type CompareItem struct {
	Rejected          bool   `json:"rejected"`
	Certified         bool   `json:"certified"`
	Malicious         bool   `json:"malicious"`
	AgentType         string `json:"agent_type"`
	ManagedAgentID    string `json:"managed_agent_id"`
	Name              string `json:"name"`
	LocalPath         string `json:"local_path,omitempty"`
	LocalSignature    string `json:"local_signature,omitempty"`
	SkillID           string `json:"skill_id,omitempty"`
	VersionID         string `json:"version_id,omitempty"`
	Status            string `json:"status,omitempty"`
	ExpectedSignature string `json:"expected_signature,omitempty"`
	Allowed           bool   `json:"allowed"`
	Reason            string `json:"reason"`
}

type Policy struct {
	Classification   *ClassificationPolicy `json:"classification,omitempty"`
	Mode             string                `json:"mode"`
	GovernanceMode   string                `json:"governance_mode"`
	LightScanSeconds int                   `json:"light_scan_seconds"`
	FullScanSeconds  int                   `json:"full_scan_seconds"`
	ReleasePublicKey string                `json:"release_public_key"`
	AgentBindings    map[string]string     `json:"agent_bindings"`
	AgentProfiles    []AgentProfile        `json:"agent_profiles,omitempty"`
}

type AgentProfile struct {
	LocalAgentID       string   `json:"local_agent_id"`
	AgentType          string   `json:"agent_type"`
	ManagedAgentID     string   `json:"managed_agent_id"`
	DefaultModel       string   `json:"default_model,omitempty"`
	AllowedModels      []string `json:"allowed_models,omitempty"`
	AllowedMCPGateways []string `json:"allowed_mcp_gateways,omitempty"`
	AutoApplySupported bool     `json:"auto_apply_supported"`
}

type Task struct {
	ID       int64          `json:"id"`
	TaskType string         `json:"task_type"`
	Payload  map[string]any `json:"payload"`
}

type SkillActionRequest struct {
	RequestID               string `json:"request_id"`
	Action                  string `json:"action"`
	AgentType               string `json:"agent_type"`
	LocalAgentID            string `json:"local_agent_id,omitempty"`
	Path                    string `json:"path"`
	ExpectedSignature       string `json:"expected_signature"`
	VersionID               string `json:"version_id,omitempty"`
	QuarantineID            string `json:"quarantine_id,omitempty"`
	ExpectedTargetSignature string `json:"expected_target_signature,omitempty"`
}

func (api API) RequestSkillAction(ctx context.Context, clientID string, request SkillActionRequest) (Task, error) {
	var task Task
	err := api.postJSON(ctx, "/api/v1/clients/"+clientID+"/skill-actions", request, &task)
	return task, err
}

type AvailableSkill struct {
	SkillID                string `json:"skill_id"`
	VersionID              string `json:"version_id,omitempty"`
	VersionNo              int    `json:"version_no,omitempty"`
	SourceVersion          string `json:"source_version,omitempty"`
	LatestTrustedVersionID string `json:"latest_trusted_version_id,omitempty"`
	Name                   string `json:"name"`
	SubmittedBy            string `json:"submitted_by,omitempty"`
	SubmittedAt            string `json:"submitted_at,omitempty"`
}

type SkillPreview struct {
	SkillID       string `json:"skill_id"`
	VersionID     string `json:"version_id,omitempty"`
	VersionNo     int    `json:"version_no,omitempty"`
	SourceVersion string `json:"source_version,omitempty"`
	Name          string `json:"name"`
	Description   string `json:"description"`
	Status        string `json:"status"`
	RiskLevel     string `json:"risk_level,omitempty"`
	SubmittedBy   string `json:"submitted_by,omitempty"`
	SubmittedAt   string `json:"submitted_at,omitempty"`
}

func NewAPI(server, token string, timeout time.Duration) API {
	return API{
		server: strings.TrimRight(server, "/"),
		token:  strings.TrimSpace(token),
		http:   &http.Client{Timeout: timeout},
	}
}

func (api API) Register(ctx context.Context, inventory Inventory) error {
	return api.post(ctx, "/api/v1/clients/register", inventory)
}

func (api API) ReportInventory(ctx context.Context, inventory Inventory) error {
	return api.post(ctx, "/api/v1/clients/"+inventory.ClientID+"/inventory", map[string]any{"agents": inventory.Agents, "recovery": inventory.Recovery})
}

func (api API) Compare(ctx context.Context, inventory Inventory, mappings map[string]string) ([]CompareItem, error) {
	agents := []map[string]any{}
	for _, agent := range inventory.Agents {
		managedAgentID := strings.TrimSpace(mappings[agent.AgentType])
		if !agent.SkillManagementSupported {
			continue
		}
		agents = append(agents, map[string]any{
			"agent_type":       agent.AgentType,
			"managed_agent_id": managedAgentID,
			"skills":           agent.Skills,
		})
	}
	var response struct {
		Items []CompareItem `json:"items"`
	}
	if err := api.postJSON(ctx, "/api/v1/clients/"+inventory.ClientID+"/compare", map[string]any{"agents": agents}, &response); err != nil {
		return nil, err
	}
	return response.Items, nil
}

func (api API) Policy(ctx context.Context, clientID string) (Policy, error) {
	var result Policy
	err := api.getJSON(ctx, "/api/v1/clients/"+clientID+"/policy", &result)
	return result, err
}

func (api API) Tasks(ctx context.Context, clientID string) ([]Task, error) {
	var result []Task
	err := api.getJSON(ctx, "/api/v1/clients/"+clientID+"/tasks", &result)
	return result, err
}

func (api API) WaitTasks(ctx context.Context, clientID string, afterID int64) ([]Task, error) {
	client := *api.http
	client.Timeout = 40 * time.Second
	api.http = &client
	var result []Task
	err := api.getJSON(ctx, fmt.Sprintf("/api/v1/clients/%s/tasks?wait_seconds=30&after_id=%d", clientID, afterID), &result)
	return result, err
}

func (api API) ReportExecutedTask(ctx context.Context, clientID string, task Task, status, taskError string) error {
	body := map[string]any{"status": status, "error": taskError}
	if task.TaskType == "sync_policy" && status == "succeeded" {
		body["applied_policy_version"] = stringValue(task.Payload, "target_version")
	}
	return api.post(ctx, fmt.Sprintf("/api/v1/clients/%s/tasks/%d/result", clientID, task.ID), body)
}

func (api API) ReportTask(ctx context.Context, clientID string, taskID int64, status, taskError string) error {
	return api.post(ctx, fmt.Sprintf("/api/v1/clients/%s/tasks/%d/result", clientID, taskID), map[string]any{
		"status": status,
		"error":  taskError,
	})
}

func (api API) StartTask(ctx context.Context, clientID string, taskID int64) (bool, string, error) {
	var result struct {
		Ignored bool   `json:"ignored"`
		Status  string `json:"status"`
	}
	err := api.postJSON(ctx, fmt.Sprintf("/api/v1/clients/%s/tasks/%d/result", clientID, taskID), map[string]any{"status": "running", "error": ""}, &result)
	if result.Status == "" && result.Ignored {
		result.Status = "cancelled"
	}
	return !result.Ignored && err == nil, result.Status, err
}

func (api API) IssueAgentCredential(ctx context.Context, clientID string, taskID int64) (AgentCredential, error) {
	var result AgentCredential
	err := api.postJSON(
		ctx,
		fmt.Sprintf("/api/v1/clients/%s/tasks/%d/agent-credential", clientID, taskID),
		map[string]any{},
		&result,
	)
	return result, err
}

func (api API) RequestModelConfiguration(ctx context.Context, clientID, localAgentID, agentType, managedAgentID, model string) (Task, error) {
	var result Task
	err := api.postJSON(
		ctx,
		"/api/v1/clients/"+clientID+"/model-configurations",
		map[string]any{
			"local_agent_id":   strings.TrimSpace(localAgentID),
			"agent_type":       strings.TrimSpace(agentType),
			"managed_agent_id": strings.TrimSpace(managedAgentID),
			"model":            strings.TrimSpace(model),
		},
		&result,
	)
	return result, err
}

func (api API) ReportEvent(ctx context.Context, clientID, eventType, agentType, skillName string, details map[string]any) error {
	if details == nil {
		details = map[string]any{}
	}
	count := details["observation_count"]
	if count == nil {
		count = 1
	}
	return api.post(ctx, "/api/v1/clients/"+clientID+"/events", map[string]any{
		"event_type":        eventType,
		"agent_type":        agentType,
		"skill_name":        skillName,
		"details":           details,
		"observation_count": count,
		"observed_at":       details["last_seen_at"],
	})
}

func (api API) ReportTakeover(ctx context.Context, clientID, backup string, managedCount, pendingCount int) error {
	return api.post(ctx, "/api/v1/clients/"+clientID+"/takeover-report", map[string]any{
		"backup":        backup,
		"managed_count": managedCount,
		"pending_count": pendingCount,
	})
}

func (api API) Heartbeat(ctx context.Context, inventory Inventory) (Policy, error) {
	var response struct {
		Policy Policy `json:"policy"`
	}
	err := api.postJSON(ctx, "/api/v1/clients/"+inventory.ClientID+"/heartbeat", map[string]any{
		"governance_protocol": 2,
		"client_id":           inventory.ClientID,
		"client_version":      inventory.ClientVersion,
	}, &response)
	return response.Policy, err
}

func (api API) DownloadPackage(ctx context.Context, clientID, skillID, agentType, managedAgentID string) ([]byte, error) {
	return api.DownloadPackageVersion(ctx, clientID, skillID, "", agentType, managedAgentID)
}

func (api API) DownloadPackageVersion(ctx context.Context, clientID, skillID, versionID, agentType, managedAgentID string) ([]byte, error) {
	query := url.Values{"agent_type": []string{agentType}}
	if managedAgentID != "" {
		query.Set("managed_agent_id", managedAgentID)
	}
	if versionID != "" {
		query.Set("version_id", versionID)
	}
	path := fmt.Sprintf("/api/v1/clients/%s/skills/%s/package?%s", clientID, skillID, query.Encode())
	request, err := api.request(ctx, http.MethodGet, path, nil)
	if err != nil {
		return nil, err
	}
	response, err := api.http.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		detail, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return nil, fmt.Errorf("Agent Manager 返回 %s: %s", response.Status, strings.TrimSpace(string(detail)))
	}
	return io.ReadAll(io.LimitReader(response.Body, 100*1024*1024))
}

type SkillVersion struct {
	VersionID     string `json:"version_id"`
	VersionNo     int    `json:"version_no"`
	SourceVersion string `json:"source_version,omitempty"`
	Status        string `json:"status"`
	RiskLevel     string `json:"risk_level,omitempty"`
	LatestTrusted bool   `json:"latest_trusted"`
	ApprovedAt    string `json:"approved_at,omitempty"`
	ApprovedBy    string `json:"approved_by,omitempty"`
	SubmittedAt   string `json:"submitted_at,omitempty"`
	SubmittedBy   string `json:"submitted_by,omitempty"`
}

type SkillVersions struct {
	SkillID          string         `json:"skill_id"`
	DefaultVersionID string         `json:"default_version_id"`
	Items            []SkillVersion `json:"items"`
}

func (api API) SkillVersions(ctx context.Context, clientID, skillID, agentType, managedAgentID string) (SkillVersions, error) {
	query := url.Values{"agent_type": []string{agentType}}
	if managedAgentID != "" {
		query.Set("managed_agent_id", managedAgentID)
	}
	var result SkillVersions
	err := api.getJSON(ctx, fmt.Sprintf("/api/v1/clients/%s/skills/%s/versions?%s", clientID, skillID, query.Encode()), &result)
	return result, err
}

func (api API) AvailableSkills(ctx context.Context, clientID, agentType, managedAgentID, search, skillID string) ([]AvailableSkill, error) {
	query := url.Values{"agent_type": []string{agentType}}
	if managedAgentID != "" {
		query.Set("managed_agent_id", managedAgentID)
	}
	if search != "" {
		query.Set("q", search)
	}
	if skillID != "" {
		query.Set("skill_id", skillID)
	}
	var result struct {
		Items []AvailableSkill `json:"items"`
	}
	err := api.getJSON(ctx, fmt.Sprintf("/api/v1/clients/%s/skills/available?%s", clientID, query.Encode()), &result)
	return result.Items, err
}

func (api API) SkillPreview(ctx context.Context, clientID, skillID, versionID, agentType, managedAgentID string) (SkillPreview, error) {
	query := url.Values{"agent_type": []string{agentType}}
	if managedAgentID != "" {
		query.Set("managed_agent_id", managedAgentID)
	}
	if versionID != "" {
		query.Set("version_id", versionID)
	}
	var result SkillPreview
	err := api.getJSON(ctx, fmt.Sprintf("/api/v1/clients/%s/skills/%s/preview?%s", clientID, skillID, query.Encode()), &result)
	return result, err
}

func (api API) post(ctx context.Context, path string, payload any) error {
	return api.postJSON(ctx, path, payload, nil)
}

func (api API) postJSON(ctx context.Context, path string, payload any, result any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	request, err := api.request(ctx, http.MethodPost, path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	response, err := api.http.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		detail, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return fmt.Errorf("Agent Manager 返回 %s: %s", response.Status, strings.TrimSpace(string(detail)))
	}
	if result != nil {
		if err := json.NewDecoder(response.Body).Decode(result); err != nil {
			return err
		}
	}
	return nil
}

func (api API) getJSON(ctx context.Context, path string, result any) error {
	request, err := api.request(ctx, http.MethodGet, path, nil)
	if err != nil {
		return err
	}
	response, err := api.http.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		detail, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return fmt.Errorf("Agent Manager 返回 %s: %s", response.Status, strings.TrimSpace(string(detail)))
	}
	return json.NewDecoder(response.Body).Decode(result)
}

func (api API) request(ctx context.Context, method, path string, body io.Reader) (*http.Request, error) {
	request, err := http.NewRequestWithContext(ctx, method, api.server+path, body)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Authorization", "Bearer "+api.token)
	return request, nil
}
