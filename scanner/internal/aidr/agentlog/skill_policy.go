package agentlog

type SkillAlertRules struct {
	ContentChanged string `json:"content_changed"`
	Approval       string `json:"approval"`
	Unauthorized   string `json:"unauthorized"`
}

// SkillAuditPolicy is negotiated with the platform; it never controls a tool decision.
type SkillAuditPolicy struct {
	Enabled              bool            `json:"enabled"`
	Alerts               bool            `json:"alerts"`
	CheckMode            string          `json:"check_mode"`
	DigestCacheSeconds   int             `json:"digest_cache_seconds"`
	StatusRefreshSeconds int             `json:"status_refresh_seconds"`
	MaxConcurrency       int             `json:"max_concurrency"`
	MaxFiles             int             `json:"max_files"`
	MaxFileBytes         int64           `json:"max_file_bytes"`
	MaxTotalBytes        int64           `json:"max_total_bytes"`
	AlertRules           SkillAlertRules `json:"alert_rules"`
}

func DefaultSkillAuditPolicy() SkillAuditPolicy {
	return SkillAuditPolicy{true, true, "on_change", 300, 30, 1, 256, 2 << 20, 8 << 20, SkillAlertRules{"alert", "alert", "alert"}}
}

func (p SkillAuditPolicy) Valid() bool {
	if (p.CheckMode != "on_change" && p.CheckMode != "every_use") || p.DigestCacheSeconds < 60 || p.DigestCacheSeconds > 3600 || p.StatusRefreshSeconds < 5 || p.StatusRefreshSeconds > 3600 || p.MaxConcurrency < 1 || p.MaxConcurrency > 8 || p.MaxFiles < 1 || p.MaxFiles > 10000 || p.MaxFileBytes < 1<<20 || p.MaxFileBytes > 100<<20 || p.MaxTotalBytes < p.MaxFileBytes || p.MaxTotalBytes > 1<<30 {
		return false
	}
	for _, action := range []string{p.AlertRules.ContentChanged, p.AlertRules.Approval, p.AlertRules.Unauthorized} {
		if action != "record" && action != "alert" {
			return false
		}
	}
	return true
}
