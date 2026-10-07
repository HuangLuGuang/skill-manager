package hooks

import (
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"regexp"
	products "skill-manager/scanner/internal/aidr/catalog"
	"time"
)

// BridgeGap retains only the latest observed intake failure. It is not an
// event receipt, an exact loss count, or evidence of tool execution.
type BridgeGap struct {
	Code       string `json:"code"`
	Cause      string `json:"cause"`
	Agent      string `json:"agent"`
	Hook       string `json:"hook"`
	ObservedAt string `json:"observed_at"`
}

var bridgeCode = regexp.MustCompile(`^aidr_[a-z0-9_]{1,100}$`)
var bridgeHook = regexp.MustCompile(`^[A-Za-z]{1,40}$`)

func BridgeFailureCode(value string) string {
	if bridgeCode.MatchString(value) {
		return value
	}
	return "aidr_hook_protocol_invalid"
}

func ValidateBridgePrivateFile(path string) error {
	if !filepath.IsAbs(path) {
		return code("aidr_hook_gap_report_failed")
	}
	dir := filepath.Dir(path)
	real, err := filepath.EvalSymlinks(dir)
	info, statErr := os.Lstat(dir)
	if err != nil || real != dir || statErr != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 || !ownedBy(info, uint32(os.Geteuid())) {
		return code("aidr_hook_gap_report_failed")
	}
	info, err = os.Lstat(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || !ownedBy(info, uint32(os.Geteuid())) {
		return code("aidr_hook_gap_report_failed")
	}
	return nil
}

func WriteBridgeGap(path, agent, hook, cause string) error {
	if ValidateBridgePrivateFile(path) != nil || !products.Hook(agent) || !bridgeHook.MatchString(hook) || !bridgeCode.MatchString(cause) {
		return code("aidr_hook_gap_report_failed")
	}
	data, _ := json.Marshal(BridgeGap{"aidr_hook_audit_gap", cause, agent, hook, time.Now().UTC().Format(time.RFC3339Nano)})
	f, err := os.CreateTemp(filepath.Dir(path), ".bridge-gap-")
	if err != nil {
		return code("aidr_hook_gap_report_failed")
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if _, err = f.Write(data); err == nil {
		err = f.Sync()
	}
	if closeErr := f.Close(); err == nil {
		err = closeErr
	}
	if err == nil {
		err = os.Rename(f.Name(), path)
	}
	if err != nil {
		return code("aidr_hook_gap_report_failed")
	}
	return nil
}

func ReadBridgeGap(path string) (*BridgeGap, error) {
	if filepath.IsAbs(path) {
		if _, err := os.Lstat(path); os.IsNotExist(err) {
			return nil, nil
		}
	}
	if ValidateBridgePrivateFile(path) != nil {
		return nil, code("aidr_hook_gap_report_failed")
	}
	f, err := os.Open(path)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, code("aidr_hook_gap_report_failed")
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, 1025))
	var gap BridgeGap
	if err != nil || len(b) > 1024 || json.Unmarshal(b, &gap) != nil || gap.Code != "aidr_hook_audit_gap" || !bridgeCode.MatchString(gap.Cause) || !products.Hook(gap.Agent) || !bridgeHook.MatchString(gap.Hook) {
		return nil, code("aidr_hook_gap_report_failed")
	}
	if _, err := time.Parse(time.RFC3339Nano, gap.ObservedAt); err != nil {
		return nil, code("aidr_hook_gap_report_failed")
	}
	return &gap, nil
}
