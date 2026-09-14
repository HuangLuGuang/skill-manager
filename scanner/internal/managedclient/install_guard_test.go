package managedclient

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestInstallRejectsUnsafeTaskIdentifiersBeforeDownload(t *testing.T) {
	for _, value := range []string{"../outside", "..", ".", "/absolute", `..\outside`, "C:outside", "bad\x00name"} {
		for _, version := range []bool{false, true} {
			skillID, versionID := value, ""
			if version {
				skillID, versionID = "skill-1", value
			}
			err := InstallApprovedSkillVersion(context.Background(), t.TempDir(), Inventory{}, Policy{}, API{}, nil, "codex", "", skillID, versionID)
			if err == nil || err.Error() != "invalid install identifier" {
				t.Fatalf("unsafe task identifier %q: %v", value, err)
			}
		}
	}
}

func TestInstallRetainsLegacyReleaseDirectory(t *testing.T) {
	for _, edit := range []bool{false, true} {
		t.Run(map[bool]string{false: "upgrade", true: "edit-during-download"}[edit], func(t *testing.T) {
			home, store, inventory, _ := observedFixture(t)
			alias := filepath.Join(ManagedSkillsRoot(home), "skill-1", "release")
			writeSkill(t, alias, "legacy-content")
			original, err := os.ReadFile(filepath.Join(alias, "SKILL.md"))
			if err != nil {
				t.Fatal(err)
			}
			public, private, err := ed25519.GenerateKey(rand.Reader)
			if err != nil {
				t.Fatal(err)
			}
			body := signedPackage(t, private)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.Contains(r.URL.Path, "/package") {
					if edit {
						if err := os.WriteFile(filepath.Join(alias, "SKILL.md"), []byte("new edit"), 0600); err != nil {
							t.Error(err)
						}
					}
					w.Write(body)
					return
				}
				w.Write([]byte(`{}`))
			}))
			defer server.Close()
			err = InstallApprovedSkill(context.Background(), home, inventory, Policy{ReleasePublicKey: base64.StdEncoding.EncodeToString(public)}, NewAPI(server.URL, "test", time.Second), store, "codex", "", "skill-1")
			if edit {
				if err == nil || err.Error() != "skill_content_changed" {
					t.Fatalf("expected conflict, got %v", err)
				}
				content, err := os.ReadFile(filepath.Join(alias, "SKILL.md"))
				if err != nil || string(content) != "new edit" {
					t.Fatalf("edit lost: %q %v", content, err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if _, err := os.Readlink(alias); err != nil {
				t.Fatal(err)
			}
			backups, err := ListBackups(home)
			if err != nil || len(backups) != 1 {
				t.Fatalf("legacy backup missing: %v %v", backups, err)
			}
			content, err := os.ReadFile(filepath.Join(backups[0].Path, "codex", "safe-skill", "SKILL.md"))
			if err != nil || string(content) != string(original) {
				t.Fatalf("legacy content lost: %q %v", content, err)
			}
		})
	}
}

func TestQueuedInstallAdoptsSameContentFromPreviousManagedIdentity(t *testing.T) {
	home := t.TempDir()
	skillsRoot := filepath.Join(home, ".codex", "skills")
	oldRelease := filepath.Join(ManagedSkillsRoot(home), "previous-skill", "versions", "previous-version", "release")
	if err := os.MkdirAll(oldRelease, 0o755); err != nil {
		t.Fatal(err)
	}
	content := []byte("---\nname: safe-skill\n---\n")
	if err := os.WriteFile(filepath.Join(oldRelease, "SKILL.md"), content, 0o644); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(skillsRoot, "safe-skill")
	if err := os.MkdirAll(skillsRoot, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(oldRelease, link); err != nil {
		t.Fatal(err)
	}

	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	packageBody := signedPackage(t, private)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/package") {
			_, _ = w.Write(packageBody)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/events") {
			_, _ = w.Write([]byte(`{"ok":true}`))
			return
		}
		t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
	}))
	defer server.Close()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	state, err := inspectInstallTarget(link)
	if err != nil {
		t.Fatal(err)
	}
	queued := map[string]any{
		"expected_root":    skillsRoot,
		"expected_path":    link,
		"expected_targets": map[string]any{link: state.signature},
	}
	inventory := Inventory{ClientID: "host", Agents: []Agent{{AgentType: "codex", SkillsPath: skillsRoot, SkillManagementSupported: true}}}
	policy := Policy{ReleasePublicKey: base64.StdEncoding.EncodeToString(public)}
	if err := installApprovedSkillVersion(context.Background(), home, inventory, policy, NewAPI(server.URL, "token", time.Second), store, "codex", "", "skill-1", "", false, queued); err != nil {
		t.Fatal(err)
	}

	resolved, err := filepath.EvalSymlinks(link)
	if err != nil {
		t.Fatal(err)
	}
	want, err := filepath.EvalSymlinks(filepath.Join(ManagedSkillsRoot(home), "skill-1", "release"))
	if err != nil {
		t.Fatal(err)
	}
	if resolved != want {
		t.Fatalf("same-content managed link was not adopted: got %s want %s", resolved, want)
	}
	installs, err := store.Installations()
	if err != nil || len(installs) != 1 || installs[0].SkillID != "skill-1" {
		t.Fatalf("new managed identity was not saved: %#v %v", installs, err)
	}
}

func TestSignedPackageRejectsUnsafeInstallMetadata(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"skill_id", "version_id", "name"} {
		for _, value := range []string{"../outside", "..", ".", "/absolute", `..\outside`, "C:outside"} {
			t.Run(field+"="+value, func(t *testing.T) {
				metadata := map[string]any{"skill_id": "skill-1", "version_id": "v1", "name": "safe-skill", "files": []any{}}
				metadata[field] = value
				body, err := json.Marshal(metadata)
				if err != nil {
					t.Fatal(err)
				}
				var buffer bytes.Buffer
				archive := zip.NewWriter(&buffer)
				writeZip(t, archive, "manifest.json", body)
				writeZip(t, archive, "manifest.sig", []byte(base64.StdEncoding.EncodeToString(ed25519.Sign(private, body))))
				if err := archive.Close(); err != nil {
					t.Fatal(err)
				}
				target := filepath.Join(t.TempDir(), "incoming")
				_, err = VerifyAndExtractPackage(buffer.Bytes(), base64.StdEncoding.EncodeToString(public), target)
				if err == nil || err.Error() != "invalid release identifier" {
					t.Fatalf("unsafe signed metadata accepted: %v", err)
				}
				if _, err := os.Lstat(target); !os.IsNotExist(err) {
					t.Fatalf("invalid package created extraction target: %v", err)
				}
			})
		}
	}
}

func TestInstallChecksTargetBeforeChangingSharedRelease(t *testing.T) {
	home := t.TempDir()
	codex := filepath.Join(home, ".codex", "skills")
	hermes := filepath.Join(home, ".hermes", "skills")
	for _, path := range []string{codex, hermes} {
		if err := os.MkdirAll(path, 0700); err != nil {
			t.Fatal(err)
		}
	}
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	packageBody := signedPackage(t, private)
	var editDuringDownload atomic.Bool
	installed := filepath.Join(codex, "safe-skill", "SKILL.md")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/package") {
			if editDuringDownload.Load() {
				if err := os.WriteFile(installed, []byte("user edit during download"), 0600); err != nil {
					t.Error(err)
				}
			}
			w.Write(packageBody)
		} else {
			w.Write([]byte(`{}`))
		}
	}))
	defer server.Close()
	store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	api := NewAPI(server.URL, "token", time.Second)
	policy := Policy{ReleasePublicKey: base64.StdEncoding.EncodeToString(public)}
	inventory := Inventory{ClientID: "host", Agents: []Agent{{AgentType: "codex", SkillsPath: codex, SkillManagementSupported: true}, {AgentType: "hermes", SkillsPath: hermes, SkillManagementSupported: true}}}
	if err := InstallApprovedSkill(context.Background(), home, inventory, policy, api, store, "codex", "", "skill-1"); err != nil {
		t.Fatal(err)
	}
	original, err := inspectInstallTarget(filepath.Dir(installed))
	if err != nil {
		t.Fatal(err)
	}
	queued := map[string]any{"expected_root": codex, "expected_targets": map[string]any{filepath.Dir(installed): original.signature}}
	editDuringDownload.Store(true)
	if err := InstallApprovedSkill(context.Background(), home, inventory, policy, api, store, "codex", "", "skill-1"); err == nil || err.Error() != "skill_content_changed" {
		t.Fatal("download-time edit was overwritten", err)
	}
	editDuringDownload.Store(false)
	if err := installApprovedSkillVersion(context.Background(), home, inventory, policy, api, store, "codex", "", "skill-1", "", true, queued); err == nil || err.Error() != "skill_content_changed" {
		t.Fatal("queued repair overwrote content edited after task creation", err)
	}
	alias := filepath.Join(ManagedSkillsRoot(home), "skill-1", "release")
	previousAlias, err := os.Readlink(alias)
	if err != nil {
		t.Fatal(err)
	}
	if err := InstallApprovedSkill(context.Background(), home, inventory, policy, api, store, "hermes", "", "skill-1"); err != nil {
		t.Fatal("independent trusted installation failed", err)
	}
	if body, err := os.ReadFile(filepath.Join(hermes, "safe-skill", "SKILL.md")); err != nil || string(body) != "---\nname: safe-skill\n---\n" {
		t.Fatal("new Agent did not receive trusted content", err)
	}
	if current, err := os.Readlink(alias); err != nil || current != previousAlias {
		t.Fatal("installation redirected existing shared alias", current, err)
	}
	conflict := filepath.Join(hermes, "safe-skill")
	if err := os.Remove(conflict); err != nil {
		t.Fatal(err)
	}
	if _, err := store.db.Exec(`DELETE FROM client_installs WHERE agent_type = 'hermes'`); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(conflict, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(conflict, "SKILL.md"), []byte("another local skill"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := InstallApprovedSkill(context.Background(), home, inventory, policy, api, store, "hermes", "", "skill-1"); err == nil {
		t.Fatal("same-name conflict was ignored")
	}
	if body, err := os.ReadFile(installed); err != nil || string(body) != "user edit during download" {
		t.Fatal("rejected install changed another Agent", err)
	}
	if body, err := os.ReadFile(filepath.Join(conflict, "SKILL.md")); err != nil || string(body) != "another local skill" {
		t.Fatal("conflicting local skill changed", err)
	}
	if err := installApprovedSkillVersion(context.Background(), home, inventory, policy, api, store, "codex", "", "skill-1", "", true); err != nil {
		t.Fatal("legacy repair failed", err)
	}
	if body, err := os.ReadFile(installed); err != nil || string(body) != "---\nname: safe-skill\n---\n" {
		t.Fatal("repair did not restore package content", err)
	}
	backups, err := ListBackups(home)
	if err != nil || len(backups) != 1 {
		t.Fatal("repair discarded original content", backups, err)
	}
	for _, backup := range backups {
		body, err := os.ReadFile(filepath.Join(backup.Path, "codex", "safe-skill", "SKILL.md"))
		if err != nil || string(body) != "user edit during download" {
			t.Fatal("backup does not contain replaced content", err)
		}
		metadata, err := os.ReadFile(filepath.Join(backup.Path, "metadata.json"))
		var fields map[string]any
		if err != nil || json.Unmarshal(metadata, &fields) != nil || fields["original_path"] != filepath.Dir(installed) || fields["signature"] == "" {
			t.Fatal("backup missing recovery provenance", string(metadata), err)
		}
	}
}

func TestInstallMaliciousVersionRespectsEffectivePolicy(t *testing.T) {
	for _, action := range []string{"record", "quarantine", "uninstall"} {
		t.Run(action, func(t *testing.T) {
			home := t.TempDir()
			public, private, err := ed25519.GenerateKey(rand.Reader)
			if err != nil {
				t.Fatal(err)
			}
			body := signedPackage(t, private)
			downloaded := false
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch {
				case strings.HasSuffix(r.URL.Path, "/preview"):
					w.Write([]byte(`{"risk_level":"malicious","status":"APPROVED"}`))
				case strings.HasSuffix(r.URL.Path, "/package"):
					downloaded = true
					w.Write(body)
				default:
					w.Write([]byte(`{}`))
				}
			}))
			defer server.Close()
			store, err := OpenStore(filepath.Join(home, ".agent-manager", "client.db"))
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			root := filepath.Join(home, ".codex", "skills")
			policy := Policy{ReleasePublicKey: base64.StdEncoding.EncodeToString(public), Classification: DefaultClassificationPolicy()}
			policy.Classification.Rules["malicious"] = action
			inventory := Inventory{ClientID: "host", Agents: []Agent{{AgentType: "codex", SkillsPath: root, SkillManagementSupported: true}}}
			err = InstallApprovedSkill(context.Background(), home, inventory, policy, NewAPI(server.URL, "token", time.Second), store, "codex", "", "skill-1")
			if action == "record" {
				if err != nil || !downloaded {
					t.Fatal("record policy installation failed", err)
				}
			} else {
				if err == nil || err.Error() != "skill_install_malicious" || downloaded {
					t.Fatal("destructive policy was not checked before download", err)
				}
				if _, err := os.Lstat(filepath.Join(root, "safe-skill")); !os.IsNotExist(err) {
					t.Fatal("blocked install changed target", err)
				}
			}
		})
	}
}
