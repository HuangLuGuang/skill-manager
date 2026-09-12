package managedclient

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestClassifiedPolicyActionMatrix(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	// Pin a real signed version so recovery exercises signature verification.
	raw := signedPackage(t, private)
	archive, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	writer := zip.NewWriter(&output)
	var trustedSignature string
	for _, file := range archive.File {
		reader, err := file.Open()
		if err != nil {
			t.Fatal(err)
		}
		body, err := io.ReadAll(reader)
		reader.Close()
		if err != nil {
			t.Fatal(err)
		}
		if file.Name == "manifest.sig" {
			continue
		}
		if file.Name == "manifest.json" {
			var metadata map[string]any
			if err := json.Unmarshal(body, &metadata); err != nil {
				t.Fatal(err)
			}
			metadata["version_id"] = "v1"
			trustedSignature = metadata["content_signature"].(string)
			body, err = json.Marshal(metadata)
			if err != nil {
				t.Fatal(err)
			}
			writeZip(t, writer, "manifest.sig", []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, body))))
		}
		writeZip(t, writer, file.Name, body)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	for trigger, actions := range map[string][]string{
		"unverified":                 {"record_only", "record", "submit_scan", "quarantine"},
		"malicious":                  {"record_only", "record", "quarantine", "uninstall"},
		"trusted_scan_rejected":      {"record_only", "record", "quarantine", "restore_trusted"},
		"unverified_scan_rejected":   {"record_only", "record", "quarantine"},
		"trusted_content_changed":    {"record_only", "record", "submit_scan", "quarantine", "restore_trusted"},
		"unverified_content_changed": {"record_only", "record", "submit_scan", "quarantine"},
	} {
		for _, action := range actions {
			t.Run(trigger+"/"+action, func(t *testing.T) {
				home, store, inventory, skill := observedFixture(t)
				previous := SkillObservation{}
				if trigger == "trusted_content_changed" || trigger == "trusted_scan_rejected" {
					previous = SkillObservation{Signature: trustedSignature, TrustedSignature: trustedSignature, TrustedSkillID: "skill-1", TrustedVersionID: "v1"}
				} else if trigger == "unverified_content_changed" {
					previous.Signature = "previous-content"
				}
				if strings.HasSuffix(trigger, "scan_rejected") {
					previous.Signature = skill.Signature
					previous.PendingID = "submitted-snapshot"
				}
				if err := store.SaveObservation(skill.Path, previous); err != nil {
					t.Fatal(err)
				}
				var uploads atomic.Int32
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					switch {
					case strings.HasSuffix(r.URL.Path, "/compare"):
						status := ""
						if strings.HasSuffix(trigger, "scan_rejected") {
							status = "REJECTED"
						}
						json.NewEncoder(w).Encode(map[string]any{"items": []CompareItem{{Rejected: status == "REJECTED", Status: status, ExpectedSignature: skill.Signature, AgentType: "codex", Name: skill.Name, LocalPath: skill.Path, LocalSignature: skill.Signature, Malicious: trigger == "malicious"}}})
					case strings.HasSuffix(r.URL.Path, "/package"):
						w.Write(output.Bytes())
					case r.URL.Path == "/api/v1/scanner/imports":
						uploads.Add(1)
						w.Write([]byte(`{"skill_id":"scan","version_id":"scan-v1","status":"PENDING"}`))
					default:
						w.Write([]byte(`{}`))
					}
				}))
				defer server.Close()
				policy := Policy{Classification: DefaultClassificationPolicy(), ReleasePublicKey: base64.StdEncoding.EncodeToString(public)}
				policy.Classification.Rules[trigger] = action
				api := NewAPI(server.URL, "token", time.Second)
				if err := patrolClassified(context.Background(), home, inventory, policy, api, store, true); err != nil {
					t.Fatal(err)
				}
				value, err := store.Observation(skill.Path)
				if err != nil || value.Trigger != trigger || value.Action != action || value.ActionStatus != "completed" {
					t.Fatal(value, err)
				}
				switch action {
				case "record_only", "record", "submit_scan":
					if err := checkObservedContent(skill); err != nil {
						t.Fatal("source changed", err)
					}
					if err := patrolClassified(context.Background(), home, inventory, policy, api, store, true); err != nil {
						t.Fatal(err)
					}
					if action == "submit_scan" && uploads.Load() != 1 {
						t.Fatal("scan not deduplicated", uploads.Load())
					}
				case "quarantine", "uninstall", "restore_trusted":
					copies, err := store.QuarantineItems()
					if err != nil || len(copies) != 1 {
						t.Fatal(copies, err)
					}
					if err := checkObservedContent(Skill{Path: copies[0].QuarantinePath, Signature: skill.Signature}); err != nil {
						t.Fatal("original copy lost", err)
					}
					if action == "restore_trusted" {
						if err := checkObservedContent(Skill{Path: skill.Path, Signature: trustedSignature}); err != nil {
							t.Fatal("trusted version not restored", err)
						}
					} else if _, err := os.Stat(filepath.Join(skill.Path, "SKILL.md")); !os.IsNotExist(err) {
						t.Fatal("active content not removed", err)
					}
					if action == "uninstall" && copies[0].Status != "uninstalled" {
						t.Fatal("uninstall status lost")
					}
				}
			})
		}
	}
}
