package hooks

import (
	"context"
	"encoding/json"
)

// PluginReport is latest observation telemetry, not an audit batch. A persistent
// sequence prevents an old receiver request replacing a newer restart's report.
type PluginReport struct {
	Schema   int          `json:"schema_version"`
	Stream   string       `json:"stream_id"`
	Sequence string       `json:"report_sequence"`
	Receiver string       `json:"receiver_instance"`
	Status   PluginStatus `json:"status"`
}

func (s *Store) PreparePluginReport(ctx context.Context, status PluginStatus) (PluginReport, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r := PluginReport{Schema: 1, Stream: s.stream, Receiver: s.instance, Status: status}
	if len(status.ScopeDigest) != 64 || (status.Agent != "claude" && status.Agent != "codex") {
		return r, code("aidr_plugin_config_invalid")
	}
	r.Status.Drift = nil
	// Bind the source scope to this private state without exposing local paths.
	r.Status.ScopeDigest = digest(s.key, "plugin-scope/1", []byte(status.ScopeDigest))
	err := s.db.QueryRowContext(ctx, `INSERT INTO hook_meta(key,value) VALUES('plugin_report_sequence','1') ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT) RETURNING value`).Scan(&r.Sequence)
	return r, err
}

func (r PluginReport) Bytes() []byte { raw, _ := json.Marshal(r); return raw }
