//go:build darwin

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"skill-manager/scanner/internal/managedclient"
	"strings"
	"testing"
)

func TestESEntitlementRequiresExactPlistBoolean(t *testing.T) {
	for _, test := range []struct {
		content string
		ok      bool
	}{
		{`<key>com.apple.developer.endpoint-security.client</key><true/>`, true},
		{`<key>other</key><array><string>x</string></array><key>com.apple.developer.endpoint-security.client</key><true/>`, true},
		{`<key>com.apple.developer.endpoint-security.client</key><false/>`, false},
		{`<key>com.apple.developer.endpoint-security.client</key><string>true</string>`, false},
		{`<key>com.apple.developer.endpoint-security.client</key><true>invalid</true>`, false},
		{`<key>com.apple.developer.endpoint-security.client</key><true/><key>com.apple.developer.endpoint-security.client</key><true/>`, false},
		{`<key>other</key><dict><key>com.apple.developer.endpoint-security.client</key><true/></dict>`, false},
		{`<key>com.apple.developer.endpoint-security.client</key>`, false},
	} {
		if got := hasESEntitlement([]byte(`<plist version="1.0"><dict>` + test.content + `</dict></plist>`)); got != test.ok {
			t.Fatalf("expected entitlement %v for controlled input", test.ok)
		}
	}
	if hasESEntitlement(bytes.Repeat([]byte("x"), 65537)) || hasESEntitlement([]byte("not a plist")) {
		t.Fatal("unbounded/invalid input accepted")
	}
	if signingTeam("TeamIdentifier=not set\n") != "" || signingTeam("TeamIdentifier=TESTTEAM01\n") != "TESTTEAM01" || signingTeam("prefixTeamIdentifier=TESTTEAM01") != "" {
		t.Fatal("invalid signer identity")
	}
}

func TestSystemPreflightDoesNotClaimESOrWriteState(t *testing.T) {
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: "http://127.0.0.1:9", Token: "fictional-system-check"}); err != nil {
		t.Fatal(err)
	}
	snapshot := func() map[string]string {
		values := map[string]string{}
		err := filepath.WalkDir(home, func(path string, entry os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if entry.Type().IsRegular() {
				body, err := os.ReadFile(path)
				if err != nil {
					return err
				}
				values[path] = string(body)
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
		return values
	}
	before := snapshot()
	var out bytes.Buffer
	if err := aidrDesktopContext(context.Background(), []string{"--home", home, "--action", "system-check"}, &out); err != nil {
		t.Fatal(err)
	}
	var report systemPrerequisites
	if err := json.Unmarshal(out.Bytes(), &report); err != nil {
		t.Fatal(err)
	}
	if report.Version != 1 || report.ESAuthorization != "unknown" || report.ESSubscription != "unknown" || report.Code != "aidr_system_authorization_entry_required" || len(report.Components) != 2 {
		t.Fatal("prerequisites misreported as actual activation")
	}
	if strings.Contains(out.String(), "fictional-system-check") || !reflect.DeepEqual(before, snapshot()) {
		t.Fatal("inspection exposed a credential or modified state")
	}
}

func TestMissingAndUnreadableEntitlementsRemainDistinct(t *testing.T) {
	if value := entitlementPermission([]byte(`<plist><dict/></plist>`)); value == nil || *value {
		t.Fatal("confirmed absence not represented")
	}
	if entitlementPermission([]byte(`unsupported output`)) != nil {
		t.Fatal("unsupported format reported as absence")
	}
	if entitlementPermission([]byte(`<plist><dict><key>com.apple.developer.endpoint-security.client</key><string>true</string></dict></plist>`)) != nil {
		t.Fatal("unsupported value reported as boolean")
	}
}
