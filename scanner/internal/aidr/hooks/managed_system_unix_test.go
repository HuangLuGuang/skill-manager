//go:build darwin || linux

package hooks

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestManagedInstallerAtomicRecoveryAndOwnedRemoval(t *testing.T) {
	for _, agent := range []string{"codex", "claude"} {
		t.Run(agent, func(t *testing.T) {
			root := t.TempDir()
			layout := ManagedLayout{Root: filepath.Join(root, "product root"), Binary: filepath.Join(root, "product root/client"), Config: filepath.Join(root, "host/config")}
			self := filepath.Join(root, "fixture executable")
			if err := os.WriteFile(self, []byte("fictional binary"), 0700); err != nil {
				t.Fatal(err)
			}
			uid := uint32(os.Geteuid())
			if err := applyManagedAt(layout, agent, "install", self, uid, root); err != nil {
				t.Fatal(err)
			}
			if version, err := managedVersionAt(layout, uid); err != nil || version != BundledPluginVersion {
				t.Fatal("installed version evidence", version, err)
			}
			raw, err := os.ReadFile(layout.Config)
			if err != nil || !managedContains(raw, agent, layout) {
				t.Fatal(err)
			}
			if err := applyManagedAt(layout, agent, "install", self, uid, root); err != nil {
				t.Fatal(err)
			}
			again, _ := os.ReadFile(layout.Config)
			if string(raw) != string(again) {
				t.Fatal("not idempotent")
			}
			manifestPath := filepath.Join(layout.Root, agent+"-ownership.json")
			var owner managedOwnership
			body, _ := os.ReadFile(manifestPath)
			if json.Unmarshal(body, &owner) != nil {
				t.Fatal("manifest")
			}
			owner.Phase = "prepared"
			body, _ = json.Marshal(owner)
			os.WriteFile(manifestPath, body, 0600)
			if err := applyManagedAt(layout, agent, "install", self, uid, root); err != nil {
				t.Fatal("cannot recover exact preimage", err)
			}
			if agent == "codex" {
				raw = append(raw, []byte("\n[permissions]\napproval_policy = 'on-request'\n")...)
			} else {
				raw = []byte(strings.TrimSuffix(strings.TrimSpace(string(raw)), "}") + `,"env":{"COMPANY":"keep"}}`)
			}
			if err = os.WriteFile(layout.Config, raw, 0644); err != nil {
				t.Fatal(err)
			}
			if err = applyManagedAt(layout, agent, "remove", self, uid, root); err != nil {
				t.Fatal(err)
			}
			removed, _ := os.ReadFile(layout.Config)
			if strings.Contains(string(removed), "aidr-hook") || (agent == "codex" && !strings.Contains(string(removed), "on-request")) || (agent == "claude" && !strings.Contains(string(removed), "COMPANY")) {
				t.Fatal("removal damaged later administrator values", string(removed))
			}
			original, _ := os.Stat(filepath.Join(layout.Root, agent+"-original"))
			if original.Mode().Perm() != 0600 {
				t.Fatal("backup permissions")
			}
			if err = applyManagedAt(layout, agent, "install", self, uid, root); err != nil {
				t.Fatal("reinstall", err)
			}
			body, _ = os.ReadFile(manifestPath)
			json.Unmarshal(body, &owner)
			owner.Phase = "prepared"
			owner.Before = "other"
			owner.After = "other"
			body, _ = json.Marshal(owner)
			os.WriteFile(manifestPath, body, 0600)
			if err = applyManagedAt(layout, agent, "install", self, uid, root); err == nil || err.Error() != "aidr_managed_recovery_required" {
				t.Fatal("blind recovery", err)
			}
		})
	}
}

func TestManagedBinaryOwnershipAndInterruptedUpgrade(t *testing.T) {
	root := t.TempDir()
	uid := uint32(os.Geteuid())
	layout := ManagedLayout{Root: filepath.Join(root, "product"), Binary: filepath.Join(root, "product/client"), Config: filepath.Join(root, "host/settings")}
	self := filepath.Join(root, "fixture")
	os.WriteFile(self, []byte("v1 fictional executable"), 0700)
	os.MkdirAll(layout.Root, 0755)
	os.WriteFile(layout.Binary, []byte("foreign executable"), 0755)
	if err := applyManagedAt(layout, "claude", "install", self, uid, root); err == nil || err.Error() != "aidr_managed_ownership_unknown" {
		t.Fatal("overwrote unowned binary", err)
	}
	body, _ := os.ReadFile(layout.Binary)
	if string(body) != "foreign executable" {
		t.Fatal("foreign changed")
	}
	// Only the fixture is removed; no installed or customer data is reset.
	os.Remove(layout.Binary)
	if err := applyManagedAt(layout, "claude", "install", self, uid, root); err != nil {
		t.Fatal(err)
	}
	old, _ := readManagedBinaryReceipt(layout, uid)
	os.WriteFile(self, []byte("v2 fictional executable"), 0700)
	newDigest, _ := managedBinaryDigest(self, uid)
	old.Phase = "prepared"
	old.Before = old.After
	old.After = newDigest
	encoded, _ := json.Marshal(old)
	managedWrite(filepath.Join(layout.Root, "binary-ownership.json"), encoded, 0644)
	if _, err := managedVersionAt(layout, uid); err == nil || err.Error() != "aidr_managed_recovery_required" {
		t.Fatal("prepared was reported ready", err)
	}
	if err := applyManagedAt(layout, "claude", "install", self, uid, root); err != nil {
		t.Fatal("bounded recovery", err)
	}
	os.WriteFile(layout.Binary, []byte("unexpected administrator replacement"), 0755)
	if _, err := managedVersionAt(layout, uid); err == nil {
		t.Fatal("invented version")
	}
	if err := applyManagedAt(layout, "claude", "install", self, uid, root); err == nil {
		t.Fatal("overwrote changed binary")
	}
}

func TestManagedInstallerRefusesUnsafeFilesAndNonRootEntrypoint(t *testing.T) {
	root := t.TempDir()
	layout := ManagedLayout{Root: filepath.Join(root, "product"), Binary: filepath.Join(root, "product/client"), Config: filepath.Join(root, "host/settings")}
	os.MkdirAll(filepath.Dir(layout.Config), 0755)
	foreign := filepath.Join(root, "foreign")
	os.WriteFile(foreign, []byte("preserve"), 0600)
	os.Symlink(foreign, layout.Config)
	err := applyManagedAt(layout, "claude", "install", foreign, uint32(os.Geteuid()), root)
	if err == nil {
		t.Fatal("followed config symlink")
	}
	data, _ := os.ReadFile(foreign)
	if string(data) != "preserve" {
		t.Fatal("foreign file changed")
	}
	if os.Geteuid() != 0 {
		if err = ApplySystemManaged("codex", "install"); err == nil || err.Error() != "aidr_managed_authorization_required" {
			t.Fatal(err)
		}
	}
}
