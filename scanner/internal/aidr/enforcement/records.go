package enforcement

import (
	"encoding/json"
	"errors"
	"net"
	"regexp"
)

type Identity struct {
	PID     string `json:"pid"`
	Version string `json:"pidversion"`
	Start   string `json:"start_us"`
}
type Record struct {
	Network        *NetworkSnapshot `json:"network,omitempty"`
	NetworkHealth  *NetworkHealth   `json:"network_health,omitempty"`
	DetailSchema   *int             `json:"detail_schema,omitempty"`
	Schema         int              `json:"schema_version"`
	Boot           string           `json:"boot_id"`
	Monitor        string           `json:"monitor_id"`
	Sequence       string           `json:"sequence"`
	Time           string           `json:"time_ns"`
	Kind           string           `json:"kind"`
	Process        Identity         `json:"process"`
	Root           *Identity        `json:"root,omitempty"`
	Relation       string           `json:"relation"`
	Transition     string           `json:"transition"`
	Path           string           `json:"path"`
	Revision       string           `json:"revision"`
	Rule           string           `json:"rule_id"`
	Decision       string           `json:"decision"`
	Result         string           `json:"result"`
	Code           string           `json:"reason_code"`
	Command        string           `json:"command_id"`
	Latency        string           `json:"latency_us"`
	Deadline       string           `json:"deadline_remaining_us"`
	Gaps           string           `json:"gaps"`
	Argv           []string         `json:"argv,omitempty"`
	ArgvTruncated  *bool            `json:"argv_truncated,omitempty"`
	PathsTruncated *bool            `json:"paths_truncated,omitempty"`
	Cwd            string           `json:"cwd,omitempty"`
	Executable     string           `json:"executable,omitempty"`
	RootPath       string           `json:"root_path,omitempty"`
	Parent         *Identity        `json:"parent,omitempty"`
	ParentPID      string           `json:"parent_pid,omitempty"`
	ExitCode       *int             `json:"exit_code,omitempty"`
	ExitSignal     *int             `json:"exit_signal,omitempty"`
	Duration       string           `json:"duration_ms,omitempty"`
	Operation      string           `json:"operation,omitempty"`
	Destination    string           `json:"destination_path,omitempty"`
	Origin         string           `json:"activity_origin,omitempty"`
}

var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

type NetworkSnapshot struct {
	Source      string `json:"source"`
	Observation string `json:"observation_id"`
	Protocol    string `json:"protocol"`
	Direction   string `json:"direction"`
	LocalIP     string `json:"local_ip"`
	LocalPort   int    `json:"local_port"`
	RemoteIP    string `json:"remote_ip"`
	RemotePort  int    `json:"remote_port"`
	State       string `json:"state"`
}
type NetworkHealth struct {
	Source  string `json:"source"`
	State   string `json:"state"`
	Sampled string `json:"sampled_at_ns"`
}

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
	if len(data) > 65536 || strict(data, &r) != nil || r.Schema != 1 || !uuidPattern.MatchString(r.Boot) || !uuidPattern.MatchString(r.Monitor) || !r.Process.valid() || (r.Root != nil && !r.Root.valid()) || (r.Parent != nil && !r.Parent.valid()) || !codePattern.MatchString(r.Code) {
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
	if !contains(r.Kind, "network", "process", "file", "authorization", "health", "policy", "response") || !contains(r.Relation, "direct", "inherited", "unknown") || !contains(r.Transition, "", "fork", "exec", "exit", "observed") || !contains(r.Decision, "allow", "deny", "unknown") || !contains(r.Result, "unknown", "responded", "failed", "applied", "executed", "verified", "rejected", "observed") || !contains(r.Operation, "", "create", "modify", "rename", "delete") || !contains(r.Origin, "", "client_probe") || (r.Command != "" && !uuidPattern.MatchString(r.Command)) || (r.Kind == "response" && r.Command == "") || (r.Kind == "file" && r.Operation == "") {
		return r, err
	}
	for _, path := range []string{r.Path, r.Cwd, r.Executable, r.RootPath, r.Destination} {
		if len(path) > 4092 {
			return r, err
		}
	}
	if (r.Kind == "network") != (r.Network != nil) {
		return r, err
	}
	if n := r.Network; n != nil {
		if n.Source != "libproc_snapshot" || !uuidPattern.MatchString(n.Observation) || !contains(n.Protocol, "tcp", "udp") || n.Direction != "unknown" || net.ParseIP(n.LocalIP) == nil || net.ParseIP(n.RemoteIP) == nil || n.LocalPort < 0 || n.LocalPort > 65535 || n.RemotePort < 1 || n.RemotePort > 65535 || !contains(n.State, "unknown", "closed", "syn_sent", "syn_received", "established", "close_wait", "fin_wait_1", "closing", "last_ack", "fin_wait_2", "time_wait") || (n.Protocol == "udp" && n.State != "unknown") || r.Relation == "unknown" || r.Root == nil {
			return r, err
		}
	}
	if n := r.NetworkHealth; n != nil {
		_, valid := decimal(n.Sampled)
		if r.Kind != "health" || n.Source != "libproc_snapshot" || !valid || !contains(n.State, "starting", "sampled", "waiting_for_process", "partial", "permission_denied", "stopped") {
			return r, err
		}
	}
	for _, value := range []string{r.ParentPID, r.Duration} {
		if value != "" {
			if _, ok := decimal(value); !ok {
				return r, err
			}
		}
	}
	if r.ExitCode != nil && (*r.ExitCode < 0 || *r.ExitCode > 255) || r.ExitSignal != nil && (*r.ExitSignal < 1 || *r.ExitSignal > 127) || r.ExitCode != nil && r.ExitSignal != nil || len(r.Argv) > 256 {
		return r, err
	}
	if r.DetailSchema != nil && *r.DetailSchema != 1 {
		return r, err
	}
	argumentBytes := 0
	for _, argument := range r.Argv {
		argumentBytes += len(argument)
		if argumentBytes > 8192 {
			return r, err
		}
	}
	return r, nil
}
func (r Record) Bytes() []byte { data, _ := json.Marshal(r); return data }
