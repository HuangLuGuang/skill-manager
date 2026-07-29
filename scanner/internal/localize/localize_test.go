package localize

import "testing"

func TestTextUsesConfiguredLocale(t *testing.T) {
	t.Setenv("AGENT_MANAGER_SCANNER_LANG", "en-US")
	if got := Text("中文", "English"); got != "English" {
		t.Fatalf("Text() = %q, want English", got)
	}
	t.Setenv("AGENT_MANAGER_SCANNER_LANG", "zh-CN")
	if got := Text("中文", "English"); got != "中文" {
		t.Fatalf("Text() = %q, want 中文", got)
	}
}
