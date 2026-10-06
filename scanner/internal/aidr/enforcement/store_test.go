package enforcement

import (
	"context"
	"path/filepath"
	"testing"
)

func record(t *testing.T, seq string) Record {
	t.Helper()
	r, e := ParseRecord([]byte(`{"schema_version":1,"boot_id":"11111111-1111-1111-1111-111111111111","monitor_id":"22222222-2222-2222-2222-222222222222","sequence":"` + seq + `","time_ns":"1800000000000000000","kind":"health","process":{"pid":"123","pidversion":"10","start_us":"9007199254740993"},"relation":"unknown","reason_code":"aidr_enforcement_active"}`))
	if e != nil {
		t.Fatal(e)
	}
	return r
}
func TestRuntimeFrozenRecoveryAndBounds(t *testing.T) {
	ctx := context.Background()
	dir, e := filepath.EvalSymlinks(t.TempDir())
	if e != nil {
		t.Fatal(e)
	}
	dir = filepath.Join(dir, "state")
	s, e := OpenStore(dir, 2)
	if e != nil {
		t.Fatal(e)
	}
	if e = s.Guard.BindDestination(ctx, "https://platform\ndevice-one"); e != nil {
		t.Fatal(e)
	}
	if _, e = OpenStore(dir, 2); e == nil {
		t.Fatal("concurrent writer accepted")
	}
	if e = s.Append(ctx, record(t, "1")); e != nil {
		t.Fatal(e)
	}
	b, e := s.Prepare(ctx)
	if e != nil || b.Count != 1 {
		t.Fatal(e)
	}
	if e = s.Append(ctx, record(t, "2")); e != nil {
		t.Fatal(e)
	}
	if e = s.Append(ctx, record(t, "3")); e == nil {
		t.Fatal("capacity not bounded")
	}
	if e = s.Append(ctx, record(t, "2")); e != nil {
		t.Fatal("identical retry at capacity rejected", e)
	}
	if e = s.Acknowledge(ctx, "wrong-digest", b.Count); e == nil {
		t.Fatal("invalid ACK accepted")
	}
	s.Close()
	s, e = OpenStore(dir, 2)
	if e != nil {
		t.Fatal(e)
	}
	defer s.Close()
	if e = s.Guard.BindDestination(ctx, "https://platform\ndevice-two"); e == nil {
		t.Fatal("wrong destination accepted")
	}
	recovered, e := s.Prepare(ctx)
	if e != nil || string(recovered.Payload) != string(b.Payload) || recovered.Digest != b.Digest {
		t.Fatal("frozen payload changed across restart")
	}
	if e = s.Acknowledge(ctx, b.Digest, b.Count); e != nil {
		t.Fatal(e)
	}
	next, e := s.Prepare(ctx)
	if e != nil || next.Count != 1 || next.Through <= b.Through {
		t.Fatal("later event lost")
	}
	if e = s.Acknowledge(ctx, b.Digest, b.Count); e == nil {
		t.Fatal("old ACK consumed next batch")
	}
	if e = s.Acknowledge(ctx, next.Digest, next.Count); e != nil {
		t.Fatal(e)
	}
	if b, e = s.Prepare(ctx); e != nil || b != nil {
		t.Fatal("acknowledged queue not empty")
	}
}
