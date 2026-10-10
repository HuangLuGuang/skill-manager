package upload

import (
	"context"
	"skill-manager/scanner/internal/aidr/hooks"
)

func (c *Client) SendPluginStatus(ctx context.Context, s *hooks.Store, status hooks.PluginStatus) (string, error) {
	if err := c.bindHooks(s); err != nil {
		return "", err
	}
	r, err := s.PreparePluginReport(ctx, status)
	if err != nil {
		return "", err
	}
	data, result := c.post(ctx, "hook-plugin-status", r.Bytes(), nil)
	if result.Code != "" {
		return "aidr_plugin_report_failed", nil
	}
	var ack struct {
		Code     string `json:"code"`
		Stream   string `json:"stream_id"`
		Sequence string `json:"report_sequence"`
	}
	if decode(data, &ack) != nil || ack.Code != "aidr_plugin_report_received" || ack.Stream != r.Stream || ack.Sequence != r.Sequence {
		return "aidr_plugin_report_ack_invalid", nil
	}
	return ack.Code, nil
}
