package enforcement

import (
	"encoding/json"
	"errors"
	"regexp"
)

type Identity struct {
	PID     string `json:"pid"`
	Version string `json:"pidversion"`
	Start   string `json:"start_us"`
}
type Record struct {
	Schema     int       `json:"schema_version"`
	Boot       string    `json:"boot_id"`
	Monitor    string    `json:"monitor_id"`
	Sequence   string    `json:"sequence"`
	Time       string    `json:"time_ns"`
	Kind       string    `json:"kind"`
	Process    Identity  `json:"process"`
	Root       *Identity `json:"root,omitempty"`
	Relation   string    `json:"relation"`
	Transition string    `json:"transition"`
	Path       string    `json:"path"`
	Revision   string    `json:"revision"`
	Rule       string    `json:"rule_id"`
	Decision   string    `json:"decision"`
	Result     string    `json:"result"`
	Code       string    `json:"reason_code"`
	Command    string    `json:"command_id"`
	Latency    string    `json:"latency_us"`
	Deadline   string    `json:"deadline_remaining_us"`
	Gaps       string    `json:"gaps"`
}

var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
var codePattern = regexp.MustCompile(`^aidr_[a-z0-9_]{1,100}$`)

func (p Identity) valid() bool {
	pid, a := decimal(p.PID)
	version, b := decimal(p.Version)
	start, c := decimal(p.Start)
	return a && b && c && pid > 0 && pid <= 2147483647 && version <= 4294967295 && start > 0
}
func ParseRecord(data []byte) (Record, error) {
	r := Record{Revision: "0", Decision: "unknown", Result: "unknown", Latency: "0", Deadline: "0", Gaps: "0"}
	err := errors.New("aidr_enforcement_record_invalid")
	if len(data) > 16384 || strict(data, &r) != nil || r.Schema != 1 || !uuidPattern.MatchString(r.Boot) || !uuidPattern.MatchString(r.Monitor) || !r.Process.valid() || (r.Root != nil && !r.Root.valid()) || !codePattern.MatchString(r.Code) || len(r.Path) > 4092 {
		return r, err
	}
	for _, s := range []string{r.Sequence, r.Time, r.Revision, r.Latency, r.Deadline, r.Gaps} {
		if _, ok := decimal(s); !ok {
			return r, err
		}
	}
	if r.Sequence == "0" || r.Time == "0" {
		return r, err
	}
	contains := func(s string, values ...string) bool {
		for _, v := range values {
			if s == v {
				return true
			}
		}
		return false
	}
	if !contains(r.Kind, "process", "authorization", "health", "policy", "response") || !contains(r.Relation, "direct", "inherited", "unknown") || !contains(r.Transition, "", "fork", "exec", "exit") || !contains(r.Decision, "allow", "deny", "unknown") || !contains(r.Result, "unknown", "responded", "failed", "applied", "executed", "verified", "rejected") || (r.Command != "" && !uuidPattern.MatchString(r.Command)) || (r.Kind == "response" && r.Command == "") {
		return r, err
	}
	for _, ch := range r.Path {
		if ch < 32 {
			return r, err
		}
	}
	return r, nil
}
func (r Record) Bytes() []byte { data, _ := json.Marshal(r); return data }
