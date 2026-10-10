package agentlog

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"skill-manager/scanner/internal/manifest"
)

func skillFixture(t testing.TB, count, size int) string {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < count; i++ {
		name := fmt.Sprintf("file-%03d", i)
		if i == 0 {
			name = "SKILL.md"
		}
		if err := os.WriteFile(filepath.Join(root, name), []byte(strings.Repeat("a", size)), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

func observeSkill(o *SkillObserver, root string, p *SkillAuditPolicy) SkillUse {
	use := SkillUse{Behavior: "file_access", Path: filepath.ToSlash(filepath.Join(root, "SKILL.md")), Basis: "tool_input.path"}
	o.Observe(context.Background(), &use, &AuditPolicy{SkillAudit: p})
	return use
}

func TestSkillReuseExpiryAndManifestParity(t *testing.T) {
	root := skillFixture(t, 3, 1024)
	o := NewSkillObserver()
	p := DefaultSkillAuditPolicy()
	now := time.Now()
	o.now = func() time.Time { return now }
	first := observeSkill(o, root, &p)
	if first.ContentStatus != "computed" {
		t.Fatalf("%+v", first)
	}
	m, err := manifest.Build(root, manifest.Options{MaxFiles: 256, MaxFileBytes: 2 << 20, MaxTotalBytes: 8 << 20})
	if err != nil {
		t.Fatal(err)
	}
	if first.Digest != manifest.ContentSignature(m.Files) {
		t.Fatal("manifest parity")
	}
	stats := o.Stats()
	now = now.Add(time.Second)
	reused := observeSkill(o, root, &p)
	if reused.ContentStatus != "reused" || reused.CheckedAt != first.CheckedAt || reused.Digest != first.Digest || o.Stats().BytesRead != stats.BytesRead {
		t.Fatal("reuse read contents or changed observation time")
	}
	now = now.Add(300 * time.Second)
	expired := observeSkill(o, root, &p)
	if expired.ContentStatus != "computed" || expired.CheckedAt == first.CheckedAt || o.Stats().BytesRead != stats.BytesRead*2 {
		t.Fatal("expiry failed")
	}
	p.CheckMode = "every_use"
	before := o.Stats().FileReads
	observeSkill(o, root, &p)
	observeSkill(o, root, &p)
	if o.Stats().FileReads-before != 6 {
		t.Fatal("every-use skipped content")
	}
}

func TestSkillMutationInvalidatesCache(t *testing.T) {
	for _, operation := range []string{"write", "add", "remove", "rename", "same-size-restored-mtime"} {
		t.Run(operation, func(t *testing.T) {
			if operation == "same-size-restored-mtime" && runtime.GOOS == "windows" {
				t.Skip("Windows file metadata does not expose change time; bounded by full rehash TTL")
			}
			root := skillFixture(t, 2, 1024)
			o := NewSkillObserver()
			p := DefaultSkillAuditPolicy()
			first := observeSkill(o, root, &p)
			path := filepath.Join(root, "file-001")
			info, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}
			switch operation {
			case "write":
				err = os.WriteFile(path, []byte("changed"), 0600)
			case "add":
				err = os.WriteFile(filepath.Join(root, "new"), []byte("new"), 0600)
			case "remove":
				err = os.Remove(path)
			case "rename":
				err = os.Rename(path, filepath.Join(root, "renamed"))
			case "same-size-restored-mtime":
				err = os.WriteFile(path, []byte(strings.Repeat("b", 1024)), 0600)
				if err == nil {
					err = os.Chtimes(path, info.ModTime(), info.ModTime())
				}
			}
			if err != nil {
				t.Fatal(err)
			}
			next := observeSkill(o, root, &p)
			if next.ContentStatus != "computed" || next.Digest == first.Digest {
				t.Fatalf("stale observation: %+v", next)
			}
		})
	}
}

func TestSkillLimitsDisabledAndLegacy(t *testing.T) {
	root := skillFixture(t, 3, 1024)
	p := DefaultSkillAuditPolicy()
	for _, tc := range []struct {
		reason string
		mutate func(*SkillAuditPolicy)
	}{
		{"file_limit", func(p *SkillAuditPolicy) { p.MaxFiles = 2 }},
		{"file_size_limit", func(p *SkillAuditPolicy) { p.MaxFileBytes = 512 }},
		{"total_size_limit", func(p *SkillAuditPolicy) { p.MaxTotalBytes = 2048 }},
		{"audit_disabled", func(p *SkillAuditPolicy) { p.Enabled = false }},
	} {
		t.Run(tc.reason, func(t *testing.T) {
			o := NewSkillObserver()
			q := p
			tc.mutate(&q)
			use := observeSkill(o, root, &q)
			if use.ContentReason != tc.reason || use.Digest != "" || o.Stats().FileReads != 0 {
				t.Fatalf("%+v %+v", use, o.Stats())
			}
		})
	}
	o := NewSkillObserver()
	observeSkill(o, root, &p)
	p.MaxFiles = 1
	if got := observeSkill(o, root, &p); got.ContentReason != "file_limit" {
		t.Fatal("changed policy reused cache")
	}
	legacy := observeSkill(o, root, nil)
	raw, _ := json.Marshal(legacy)
	if legacy.Digest == "" || strings.Contains(string(raw), "content_status") {
		t.Fatal("legacy contract changed")
	}
}

func TestSkillMissingSymlinkTraversalAndCancellation(t *testing.T) {
	p := DefaultSkillAuditPolicy()
	o := NewSkillObserver()
	root := skillFixture(t, 1, 10)
	if got := observeSkill(o, filepath.Join(root, "missing"), &p); got.ContentReason != "source_missing" {
		t.Fatalf("%+v", got)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	use := SkillUse{Path: filepath.ToSlash(filepath.Join(root, "SKILL.md"))}
	o.Observe(ctx, &use, &AuditPolicy{SkillAudit: &p})
	if use.ContentReason != "check_cancelled" || o.Stats().FileReads != 0 {
		t.Fatal("cancelled check performed IO")
	}
	if runtime.GOOS != "windows" {
		if err := os.Symlink(filepath.Join(root, "SKILL.md"), filepath.Join(root, "link")); err != nil {
			t.Fatal(err)
		}
		if got := observeSkill(o, root, &p); got.ContentReason != "source_symlink" {
			t.Fatalf("%+v", got)
		}
		if err := os.Remove(filepath.Join(root, "link")); err != nil {
			t.Fatal(err)
		}
	}
	p.MaxFiles = 1
	for i := 0; i < 261; i++ {
		if err := os.Mkdir(filepath.Join(root, fmt.Sprintf("d%d", i)), 0700); err != nil {
			t.Fatal(err)
		}
	}
	if got := observeSkill(o, root, &p); got.ContentReason != "entry_limit" {
		t.Fatalf("%+v", got)
	}
}

func TestSkillInFlightCoalescingAndConcurrencyCancellation(t *testing.T) {
	root := skillFixture(t, 1, 16)
	p := DefaultSkillAuditPolicy()
	o := NewSkillObserver()
	entered, release := make(chan struct{}), make(chan struct{})
	var once sync.Once
	o.now = func() time.Time { once.Do(func() { close(entered); <-release }); return time.Now() }
	leader := make(chan SkillUse, 1)
	go func() { leader <- observeSkill(o, root, &p) }()
	<-entered
	waiter := make(chan SkillUse, 1)
	go func() { waiter <- observeSkill(o, root, &p) }()
	deadline := time.Now().Add(time.Second)
	for o.Stats().Coalesced == 0 && time.Now().Before(deadline) {
		runtime.Gosched()
	}
	other := skillFixture(t, 1, 16)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	use := SkillUse{Path: filepath.ToSlash(filepath.Join(other, "SKILL.md"))}
	o.Observe(ctx, &use, &AuditPolicy{SkillAudit: &p})
	close(release)
	a, b := <-leader, <-waiter
	if use.ContentReason != "check_cancelled" || a.Digest != b.Digest || b.ContentStatus != "reused" || o.Stats().FileReads != 1 || o.Stats().Coalesced != 1 {
		t.Fatalf("%+v %+v %+v %+v", a, b, use, o.Stats())
	}
}

func TestSkillCacheHasDirectoryBound(t *testing.T) {
	p := DefaultSkillAuditPolicy()
	o := NewSkillObserver()
	for i := 0; i < 130; i++ {
		root := skillFixture(t, 1, 1)
		if use := observeSkill(o, root, &p); use.Digest == "" {
			t.Fatal(use)
		}
	}
	if len(o.cache) != 128 {
		t.Fatalf("unbounded cache: %d", len(o.cache))
	}
}

func BenchmarkSkillObservation(b *testing.B) {
	root := skillFixture(b, 256, 32768)
	for _, mode := range []string{"on_change", "every_use"} {
		b.Run(mode, func(b *testing.B) {
			p := DefaultSkillAuditPolicy()
			p.CheckMode = mode
			o := NewSkillObserver()
			if use := observeSkill(o, root, &p); use.Digest == "" {
				b.Fatal(use)
			}
			before := o.Stats()
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				if use := observeSkill(o, root, &p); use.Digest == "" {
					b.Fatal(use)
				}
			}
			b.StopTimer()
			after := o.Stats()
			b.ReportMetric(float64(after.BytesRead-before.BytesRead)/float64(b.N), "content-B/op")
		})
	}
}
