package main

import (
	"bytes"
	"context"
	"crypto/elliptic"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"

	"skill-manager/scanner/internal/managedclient"
)

func TestHookModeBootstrapPinsKey(t *testing.T) {
	x, y := elliptic.P256().ScalarBaseMult([]byte{1})
	key := elliptic.Marshal(elliptic.P256(), x, y)
	x, y = elliptic.P256().ScalarBaseMult([]byte{2})
	other := elliptic.Marshal(elliptic.P256(), x, y)
	for _, tc := range []struct {
		name            string
		prior, response []byte
		pinned          bool
		status          int
		want            string
	}{
		{"first_install", nil, key, false, 200, ""},
		{"unchanged", key, key, true, 200, ""},
		{"changed", key, other, true, 200, "aidr_hook_control_key_changed"},
		{"missing_pinned_file", nil, key, true, 200, "aidr_hook_control_key_invalid"},
		{"invalid_curve_point", nil, make([]byte, 65), false, 200, "aidr_hook_control_key_invalid"},
		{"unauthorized", key, key, true, 401, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method != "POST" || r.Header.Get("Authorization") != "Bearer fictional-token" {
					t.Error("bootstrap did not authenticate")
				}
				w.WriteHeader(tc.status)
				_ = json.NewEncoder(w).Encode(map[string]string{"public_key": base64.StdEncoding.EncodeToString(tc.response)})
			}))
			defer server.Close()
			root := t.TempDir()
			path := filepath.Join(root, "hook-policy-key.bin")
			if tc.prior != nil {
				if err := os.WriteFile(path, tc.prior, 0600); err != nil {
					t.Fatal(err)
				}
			}
			pinned := ""
			if tc.pinned {
				pinned = path
			}
			got, err := prepareHookControlKey(context.Background(), managedclient.Config{Server: server.URL, Token: "fictional-token"}, desktopPaths{Root: root, Device: "test-device"}, pinned)
			if tc.want != "" || tc.status != 200 {
				if err == nil || (tc.want != "" && err.Error() != tc.want) {
					t.Fatalf("unexpected failure: %v", err)
				}
				data, readErr := os.ReadFile(path)
				if tc.prior == nil {
					if !os.IsNotExist(readErr) {
						t.Fatal("failed bootstrap created trust file")
					}
				} else if readErr != nil || !bytes.Equal(data, tc.prior) {
					t.Fatal("failed bootstrap replaced pinned trust")
				}
				return
			}
			if err != nil || got != path {
				t.Fatal(got, err)
			}
			data, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(data, key) {
				t.Fatal("wrong pinned key", err)
			}
			info, err := os.Stat(path)
			if err != nil || info.Mode().Perm() != 0600 {
				t.Fatal("key permissions", err)
			}
		})
	}
}

func TestInterceptBootstrapFailurePreservesAppliedMode(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer server.Close()
	home := shortDesktopTestHome(t)
	if err := managedclient.SaveConfig(home, managedclient.Config{Server: server.URL, Token: "fictional-token"}); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(home, ".agent-manager", "aidr", "preferences.json")
	if err := writeDesktopJSON(path, desktopPreferences{Enabled: true, HookMode: "audit"}); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = reconcileAIDRPolicy(context.Background(), home, managedclient.Task{ID: 1, Payload: map[string]any{
		"policy_version": "1:1", "target": managedclient.RuntimeGovernancePolicy{
			Enabled: true, Installation: "manual", AccessMode: "ordinary", Updates: "manual",
			Retry: managedclient.ReceiverRetryPolicy{Mode: "none", MaxIntervalSeconds: 60},
			Modes: &managedclient.RuntimeProtectionModes{Hooks: "intercept", System: "audit"},
		},
	}})
	if err == nil || calls.Load() == 0 {
		t.Fatal("bootstrap failure was not exercised", err)
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("failed switch changed applied preferences", err)
	}
}

func TestLegacyModeMigrationPreservesAuditAndIntercept(t *testing.T) {
	for _, key := range []string{"", "/private/legacy-public-key"} {
		home := shortDesktopTestHome(t)
		path := filepath.Join(home, ".agent-manager", "aidr", "preferences.json")
		if err := writeDesktopJSON(path, map[string]any{"enabled": true, "public_key": key}); err != nil {
			t.Fatal(err)
		}
		prefs, err := loadDesktopPreferences(home)
		if err != nil {
			t.Fatal(err)
		}
		want := "audit"
		if key != "" {
			want = "intercept"
		}
		if prefs.HookMode != want {
			t.Fatal("legacy mode changed", prefs.HookMode, want)
		}
		prefs.HookMode = "audit"
		if err = writeDesktopJSON(path, prefs); err != nil {
			t.Fatal(err)
		}
		next, err := loadDesktopPreferences(home)
		if err != nil || next.HookMode != "audit" {
			t.Fatal("public key overrode explicit audit", err, next.HookMode)
		}
	}
}
