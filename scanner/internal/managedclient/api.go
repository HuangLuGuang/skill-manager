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
	server      string
	token       string
	http        *http.Client
	eventsStore *Store
}

type AgentCredential struct {
	Token              string   `json:"token"`
	TokenPrefix        string   `json:"token_prefix"`
	CredentialSource   string   `json:"credential_source,omitempty"`
	CredentialType     string   `json:"credential_type,omitempty"`
	GatewayBaseURL     string   `json:"gateway_base_url,omitempty"`
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
	OrdinaryEventsProtocol int                   `json:"ordinary_events_protocol,omitempty"`
	AgentDiscovery         *DiscoveryCatalog     `json:"agent_discovery,omitempty"`
	Classification         *ClassificationPolicy `json:"classification,omitempty"`
	Mode                   string                `json:"mode"`
	GovernanceMode         string                `json:"governance_mode"`
	LightScanSeconds       int                   `json:"light_scan_seconds"`
	FullScanSeconds        int                   `json:"full_scan_seconds"`
	ReleasePublicKey       string                `json:"release_public_key"`
	AgentBindings          map[string]string     `json:"agent_bindings"`
	AgentProfiles          []AgentProfile        `json:"agent_profiles,omitempty"`
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

type ClientUpdateVersions struct {
	Stable  string `json:"stable,omitempty"`
	Preview string `json:"preview,omitempty"`
}

type PlatformScanEvent struct {
	Revision  int64  `json:"revision"`
	PendingID string `json:"pending_id,omitempty"`
	SkillID   string `json:"skill_id,omitempty"`
	VersionID string `json:"version_id"`
	Status    string `json:"status"`
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
	RetainCopy              bool   `json:"retain_copy"`
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
	tasks, _, _, err := api.WaitTasksWithUpdatesAndScans(ctx, clientID, afterID, nil, 0)
	return tasks, err
}

func (api API) WaitTasksWithUpdates(ctx context.Context, clientID string, afterID int64) ([]Task, ClientUpdateVersions, error) {
	tasks, versions, _, err := api.WaitTasksWithUpdatesAndScans(ctx, clientID, afterID, nil, 0)
	return tasks, versions, err
}

func (api API) WaitTasksWithUpdatesAndScans(ctx context.Context, clientID string, afterID int64, scanIDs []string, scanRevision int64) ([]Task, ClientUpdateVersions, []PlatformScanEvent, error) {
	client := *api.http
	client.Timeout = 40 * time.Second
	api.http = &client
	query := url.Values{"wait_seconds": {"30"}, "after_id": {fmt.Sprintf("%d", afterID)}, "include_events": {"true"}, "scan_after_revision": {fmt.Sprintf("%d", scanRevision)}}
	if len(scanIDs) > 0 {
		query.Set("scan_ids", strings.Join(scanIDs, ","))
	}
	request, err := api.request(ctx, http.MethodGet, fmt.Sprintf("/api/v1/clients/%s/tasks?%s", clientID, query.Encode()), nil)
	if err != nil {
		return nil, ClientUpdateVersions{}, nil, err
	}
	response, err := api.http.Do(request)
	if err != nil {
		return nil, ClientUpdateVersions{}, nil, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		detail, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return nil, ClientUpdateVersions{}, nil, fmt.Errorf("Agent Manager 返回 %s: %s", response.Status, strings.TrimSpace(string(detail)))
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, ClientUpdateVersions{}, nil, err
	}
	trimmed := bytes.TrimSpace(body)
	if len(trimmed) > 0 && trimmed[0] == '[' {
		var legacy []Task
		if err := json.Unmarshal(trimmed, &legacy); err != nil {
			return nil, ClientUpdateVersions{}, nil, err
		}
		return legacy, ClientUpdateVersions{Stable: strings.TrimSpace(response.Header.Get("X-Agent-Manager-Client-Stable-Version")), Preview: strings.TrimSpace(response.Header.Get("X-Agent-Manager-Client-Preview-Version"))}, nil, nil
	}
	var envelope struct {
		Tasks      []Task              `json:"tasks"`
		ScanEvents []PlatformScanEvent `json:"scan_events"`
	}
	if err := json.Unmarshal(trimmed, &envelope); err != nil {
		return nil, ClientUpdateVersions{}, nil, err
	}
	versions := ClientUpdateVersions{
		Stable:  strings.TrimSpace(response.Header.Get("X-Agent-Manager-Client-Stable-Version")),
		Preview: strings.TrimSpace(response.Header.Get("X-Agent-Manager-Client-Preview-Version")),
	}
	return envelope.Tasks, versions, envelope.ScanEvents, nil
}

func (api API) ReportExecutedTask(ctx context.Context, clientID string, task Task, status, taskError string) error {
	body := map[string]any{"status": status, "error": taskError}
	if task.TaskType == "aidr_skill_observe" && task.Payload["skill_observation"] != nil {
		body["skill_observation"] = task.Payload["skill_observation"]
	}
	if task.TaskType == "aidr_plugin_action" && task.Payload["aidr_result"] != nil {
		body["aidr_result"] = task.Payload["aidr_result"]
	}
	if task.TaskType == "verify_model_config" {
		if ids, ok := task.Payload["verification_request_ids"]; ok {
			body["verification_request_ids"] = ids
		}
		if restored, ok := task.Payload["restored_after_failure"]; ok {
			body["restored_after_failure"] = restored
		}
	}
	if task.TaskType == "verify_model_config" || task.TaskType == "restore_model_config" {
		if model, ok := task.Payload["applied_model"]; ok {
			body["applied_model"] = model
		}
	}

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

func (api API) IssueAgentCredential(ctx context.Context, clientID string, taskID int64, previousHash ...string) (AgentCredential, error) {
	return api.IssueTaskCredential(ctx, clientID, taskID, "", previousHash...)
}

// IssueTaskCredential retrieves a secret that is bound to one authorized
// model task. The task payload only contains the source selector; the secret is
// returned by this separate authenticated request and never persisted in the
// task record.
func (api API) IssueTaskCredential(ctx context.Context, clientID string, taskID int64, credentialSource string, previousHash ...string) (AgentCredential, error) {
	var result AgentCredential
	body := map[string]any{}
	if credentialSource = strings.TrimSpace(credentialSource); credentialSource != "" {
		body["credential_source"] = credentialSource
	}
	if len(previousHash) > 0 && previousHash[0] != "" {
		body["previous_credential_hash"] = previousHash[0]
	}
	err := api.postJSON(
		ctx,
		fmt.Sprintf("/api/v1/clients/%s/tasks/%d/agent-credential", clientID, taskID),
		body,
		&result,
	)
	if err == nil && credentialSource != "" {
		if result.CredentialSource != credentialSource {
			return AgentCredential{}, fmt.Errorf("model_config.credential_source_mismatch")
		}
		if credentialSource == "external_gateway" && result.CredentialType != "external_gateway_api_key" {
			return AgentCredential{}, fmt.Errorf("model_config.credential_type_mismatch")
		}
	}
	return result, err
}

func (api API) PreflightModelTask(ctx context.Context, clientID string, taskID int64, revision string, current map[string]any) error {
	var result struct {
		OK bool `json:"ok"`
	}
	if err := api.postJSON(ctx, fmt.Sprintf("/api/v1/clients/%s/tasks/%d/model-preflight", clientID, taskID), map[string]any{"revision": revision, "current_parameters": current}, &result); err != nil {
		return err
	}
	if !result.OK {
		return fmt.Errorf("model_config.preflight_failed")
	}
	return nil
}

func (api API) RequestModelConfiguration(ctx context.Context, clientID, localAgentID, agentType, managedAgentID, model string, options ...map[string]any) (Task, error) {
	var result Task
	payload := map[string]any{"local_agent_id": strings.TrimSpace(localAgentID), "agent_type": strings.TrimSpace(agentType), "managed_agent_id": strings.TrimSpace(managedAgentID), "model": strings.TrimSpace(model)}
	if len(options) > 0 {
		for _, key := range []string{"parameters", "expected_revision"} {
			if value, ok := options[0][key]; ok {
				payload[key] = value
			}
		}
		if source := strings.TrimSpace(stringValue(options[0], "gateway_source")); source != "" {
			if source == "external" {
				source = "external_gateway"
			}
			payload["source"] = source
		}
	}
	err := api.postJSON(
		ctx,
		"/api/v1/clients/"+clientID+"/model-configurations",
		payload,
		&result,
	)
	return result, err
}

func (api API) ReportEvent(ctx context.Context, clientID, eventType, agentType, skillName string, details map[string]any) error {
	return api.sendOrdinaryEvent(ctx, QueuedEvent{ClientID: clientID, EventType: eventType, AgentType: agentType, SkillName: skillName, Details: details})
}

func (api API) ReportTakeover(ctx context.Context, clientID, backup string, managedCount, pendingCount int) error {
	return api.post(ctx, "/api/v1/clients/"+clientID+"/takeover-report", map[string]any{
		"backup":        backup,
		"managed_count": managedCount,
		"pending_count": pendingCount,
	})
}

func (api API) Heartbeat(ctx context.Context, inventory Inventory, homes ...string) (Policy, error) {
	var response struct {
		Policy Policy `json:"policy"`
	}
	body := map[string]any{
		"governance_protocol": 2,
		"client_id":           inventory.ClientID,
		"client_version":      inventory.ClientVersion,
	}
	if AIDRRuntimeSnapshot != nil && len(homes) == 1 {
		body["runtime_governance"] = AIDRRuntimeSnapshot(homes[0])
	}
	err := api.postJSON(ctx, "/api/v1/clients/"+inventory.ClientID+"/heartbeat", body, &response)
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
