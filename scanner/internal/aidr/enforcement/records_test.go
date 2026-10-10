package enforcement

import (
	"bytes"
	"strings"
	"testing"
)

func TestNetworkSnapshotContract(t *testing.T) {
	r := record(t, "1")
	r.Kind, r.Relation, r.Root = "network", "direct", &r.Process
	r.Network = &NetworkSnapshot{Source: "libproc_snapshot", Observation: "11111111-1111-1111-1111-111111111111", Protocol: "tcp", Direction: "unknown", LocalIP: "::1", LocalPort: 1234, RemoteIP: "::1", RemotePort: 8080, State: "established"}
	if _, err := ParseRecord(r.Bytes()); err != nil {
		t.Fatal(err)
	}
	for _, mutate := range []func(*Record){
		func(v *Record) { v.Network.RemoteIP = "example.com" },
		func(v *Record) { v.Network.Protocol = "udp" },
		func(v *Record) { v.Network.RemotePort = 65536 },
		func(v *Record) { v.Network.State = "failed" },
		func(v *Record) { v.Network.Direction = "outbound" },
		func(v *Record) { v.Root = nil },
		func(v *Record) { v.Relation = "unknown" },
		func(v *Record) { v.Kind = "process" },
	} {
		v, _ := ParseRecord(r.Bytes())
		mutate(&v)
		if _, err := ParseRecord(v.Bytes()); err == nil {
			t.Fatal("invalid network evidence accepted", v)
		}
	}
	r.Kind, r.Network = "health", nil
	r.NetworkHealth = &NetworkHealth{Source: "libproc_snapshot", State: "partial", Sampled: "123"}
	if _, err := ParseRecord(r.Bytes()); err != nil {
		t.Fatal(err)
	}
	r.NetworkHealth.State = "active"
	if _, err := ParseRecord(r.Bytes()); err == nil {
		t.Fatal("unconfirmed active state accepted")
	}
}

func TestOperationEvidencePreservesArgumentsAndLegacyBytes(t *testing.T) {
	legacy := record(t, "1")
	baseline := legacy.Bytes()
	parsed, err := ParseRecord(baseline)
	if err != nil || !bytes.Equal(parsed.Bytes(), baseline) {
		t.Fatal("legacy replay changed", err)
	}
	legacy.Kind, legacy.Transition = "process", "exit"
	legacy.Argv = []string{"/bin/sh", "-c", "printf '%s' 'token=verbatim-value'\nexit 7"}
	legacy.Cwd = "/private/tmp/operation"
	exit := 7
	legacy.ExitCode = &exit
	legacy.Duration = "123"
	parsed, err = ParseRecord(legacy.Bytes())
	if err != nil || parsed.Argv[2] != legacy.Argv[2] || *parsed.ExitCode != 7 {
		t.Fatal("operation evidence lost", err)
	}
	legacy.Argv = []string{strings.Repeat("x", 8193)}
	if _, err = ParseRecord(legacy.Bytes()); err == nil {
		t.Fatal("unbounded arguments accepted")
	}
	legacy.Argv = []string{strings.Repeat("\x01", 8192)}
	if _, err = ParseRecord(legacy.Bytes()); err != nil {
		t.Fatal("bounded escaped arguments rejected", err)
	}
	legacy.Kind, legacy.Operation = "file", "rename"
	legacy.Path, legacy.Destination = "/private/tmp/a\nfile", "/private/tmp/b"
	if _, err = ParseRecord(legacy.Bytes()); err != nil {
		t.Fatal(err)
	}
	legacy.Operation = ""
	if _, err = ParseRecord(legacy.Bytes()); err == nil {
		t.Fatal("file operation required")
	}
}
