//go:build darwin

package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSystemInstallInputsRejectSymlinksWritableFilesAndWrongOwner(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "request.json")
	if err := os.WriteFile(path, []byte(`{"token":"test-private"}`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := systemRead(path, os.Getuid(), 100); err != nil {
		t.Fatal(err)
	}
	if _, err := systemRead(path, os.Getuid()+1, 100); err == nil {
		t.Fatal("accepted another owner's request")
	}
	if _, err := systemRead(path, os.Getuid(), 2); err == nil {
		t.Fatal("accepted oversized request")
	}
	link := filepath.Join(root, "link")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := systemRead(link, os.Getuid(), 100); err == nil {
		t.Fatal("followed request symlink")
	}
	if err := os.Chmod(path, 0666); err != nil {
		t.Fatal(err)
	}
	if _, err := systemRead(path, os.Getuid(), 100); err == nil {
		t.Fatal("accepted writable request")
	}
}

func TestNativeStartupDiagnosticsPreservePermissionAndSubscriptionFailure(t *testing.T) {
	for _, code := range []string{"aidr_enforcement_fda_required", "aidr_enforcement_entitlement_required", "aidr_enforcement_root_required", "aidr_enforcement_subscription_failed", "aidr_enforcement_es_unavailable"} {
		d := new(nativeDiagnostics)
		_, _ = d.Write([]byte(code + ":2\n"))
		if d.code() != code {
			t.Fatal(code, d.code())
		}
	}
	d := new(nativeDiagnostics)
	_, _ = d.Write(bytes.Repeat([]byte("x"), 100000))
	if len(d.data) != 4096 || d.code() != "aidr_enforcement_native_exit" {
		t.Fatal("unbounded or unsanitized native diagnostic")
	}
}

func TestSystemCLIPrivilegeSeparationAndSafeFailure(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("requires ordinary user")
	}
	for _, action := range []string{"install-start", "run"} {
		var out bytes.Buffer
		err := aidrSystem([]string{"--action", action}, &out)
		if err == nil || err.Error() != "aidr_system_root_required" || out.Len() != 0 {
			t.Fatal(action, err, out.String())
		}
	}
	if got := systemSafeError(os.ErrPermission); got != "aidr_system_runtime_failed" {
		t.Fatal(got)
	}
	if !strings.Contains(systemEntitlement, "endpoint-security.client") {
		t.Fatal("missing signed entitlement")
	}
}
