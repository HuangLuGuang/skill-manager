package client

import "testing"

func TestScannerLocale(t *testing.T) {
	t.Setenv("LANG", "zh_CN.UTF-8")
	t.Setenv("AGENT_MANAGER_SCANNER_LANG", "")
	if got := scannerLocale(); got != "zh-CN" {
		t.Fatalf("scannerLocale() = %q, want zh-CN", got)
	}

	t.Setenv("AGENT_MANAGER_SCANNER_LANG", "en-US")
	if got := scannerLocale(); got != "en-US" {
		t.Fatalf("scannerLocale() = %q, want en-US", got)
	}
}
