//go:build darwin || linux

package hooks

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/BurntSushi/toml"
)

type managedOwnership struct {
	Version       int    `json:"version"`
	Agent         string `json:"agent"`
	Phase         string `json:"phase"`
	Before        string `json:"before"`
	After         string `json:"after"`
	AddedFeature  bool   `json:"added_feature"`
	PluginVersion string `json:"plugin_version"`
}

// Public, root-owned installation evidence contains no user configuration or
// credentials. The common executable may serve more than one managed host.
type managedBinaryReceipt struct {
	Version       int    `json:"version"`
	PluginVersion string `json:"plugin_version"`
	Phase         string `json:"phase"`
	Before        string `json:"before"`
	After         string `json:"after"`
}

func managedBinaryDigest(path string, uid uint32) (string, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if os.IsNotExist(err) {
		return "", nil
	}
	if err != nil {
		return "", code("aidr_managed_binary_invalid")
	}
	file := os.NewFile(uintptr(fd), path)
	defer file.Close()
	info, err := file.Stat()
	stat, ok := infoSys(info)
	if err != nil || !ok || !info.Mode().IsRegular() || stat.Uid != uid || info.Mode().Perm()&0022 != 0 || info.Mode().Perm()&0111 == 0 || info.Size() > 128<<20 {
		return "", code("aidr_managed_binary_invalid")
	}
	hash := sha256.New()
	if n, err := io.Copy(hash, io.LimitReader(file, (128<<20)+1)); err != nil || n != info.Size() {
		return "", code("aidr_managed_binary_invalid")
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func readManagedBinaryReceipt(layout ManagedLayout, uid uint32) (managedBinaryReceipt, error) {
	var receipt managedBinaryReceipt
	raw, _, err := readManagedFile(filepath.Join(layout.Root, "binary-ownership.json"), uid, 2048)
	if err != nil || len(raw) == 0 {
		return receipt, err
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&receipt) != nil || receipt.Version != 1 || (receipt.Phase != "ready" && receipt.Phase != "prepared") || receipt.PluginVersion == "" || len(receipt.PluginVersion) > 80 || len(receipt.After) != 64 {
		return receipt, code("aidr_managed_ownership_unknown")
	}
	return receipt, nil
}

func installManagedBinary(layout ManagedLayout, self string, uid uint32) error {
	current, err := managedBinaryDigest(layout.Binary, uid)
	if err != nil {
		return err
	}
	previous, err := readManagedBinaryReceipt(layout, uid)
	if err != nil {
		return err
	}
	if current != "" && (previous.Version == 0 || (current != previous.After && (previous.Phase != "prepared" || current != previous.Before))) {
		return code("aidr_managed_ownership_unknown")
	}
	sourceInfo, err := os.Lstat(self)
	sourceStat, ok := infoSys(sourceInfo)
	if err != nil || !ok {
		return code("aidr_desktop_binary_missing")
	}
	source, err := managedBinaryDigest(self, sourceStat.Uid)
	if err != nil {
		return err
	}
	if source == "" {
		return code("aidr_desktop_binary_missing")
	}
	receipt := managedBinaryReceipt{Version: 1, PluginVersion: BundledPluginVersion, Phase: "prepared", Before: current, After: source}
	body, _ := json.Marshal(receipt)
	path := filepath.Join(layout.Root, "binary-ownership.json")
	if err = managedWrite(path, body, 0644); err != nil {
		return err
	}
	if err = copyManagedBinary(self, layout.Binary); err != nil {
		return err
	}
	actual, err := managedBinaryDigest(layout.Binary, uid)
	if err != nil || actual != source {
		return code("aidr_managed_binary_invalid")
	}
	receipt.Phase = "ready"
	body, _ = json.Marshal(receipt)
	return managedWrite(path, body, 0644)
}

// This privileged action accepts only a host enum and a fixed operation. It
// reads no device credentials, remote commands or caller-provided target paths.
func ApplySystemManaged(agent, action string) error {
	if os.Geteuid() != 0 {
		return code("aidr_managed_authorization_required")
	}
	if action != "install" && action != "remove" {
		return code("aidr_managed_action_invalid")
	}
	layout, err := SystemManagedLayout(agent)
	if err != nil {
		return err
	}
	self, err := os.Executable()
	if err != nil {
		return code("aidr_desktop_binary_missing")
	}
	return applyManagedAt(layout, agent, action, self, 0, "/")
}

func protectedManagedDir(path, floor string, uid uint32) error {
	path = filepath.Clean(path)
	floor = filepath.Clean(floor)
	rel, err := filepath.Rel(floor, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, "../") {
		return code("aidr_managed_path_invalid")
	}
	current := floor
	for _, part := range strings.Split(rel, string(filepath.Separator)) {
		if part == "." || part == "" {
			continue
		}
		current = filepath.Join(current, part)
		if err = os.Mkdir(current, 0755); err != nil && !os.IsExist(err) {
			return code("aidr_managed_permission_denied")
		}
		info, err := os.Lstat(current)
		// /etc is the OS-owned macOS alias; no product/config symlinks are accepted.
		if err == nil && current == "/etc" && info.Mode()&os.ModeSymlink != 0 {
			resolved, e := filepath.EvalSymlinks(current)
			if e != nil || resolved != "/private/etc" {
				return code("aidr_managed_path_invalid")
			}
			info, err = os.Stat(current)
		}
		stat, ok := infoSys(info)
		if err != nil || !ok || !info.IsDir() || stat.Uid != uid || info.Mode().Perm()&0022 != 0 {
			return code("aidr_managed_path_invalid")
		}
	}
	return nil
}

func infoSys(info os.FileInfo) (*syscall.Stat_t, bool) {
	if info == nil {
		return nil, false
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	return stat, ok
}

func readManagedFile(path string, uid uint32, limit int64) ([]byte, os.FileMode, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if os.IsNotExist(err) {
		return nil, 0644, nil
	}
	if err != nil {
		return nil, 0, code("aidr_managed_config_unreadable")
	}
	file := os.NewFile(uintptr(fd), path)
	defer file.Close()
	info, err := file.Stat()
	stat, ok := infoSys(info)
	if err != nil || !ok || !info.Mode().IsRegular() || stat.Uid != uid || info.Mode().Perm()&0022 != 0 {
		return nil, 0, code("aidr_managed_path_invalid")
	}
	data, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || int64(len(data)) > limit {
		return nil, 0, code("aidr_managed_config_oversized")
	}
	return data, info.Mode().Perm(), nil
}

func managedWrite(path string, data []byte, mode os.FileMode) error {
	file, err := os.CreateTemp(filepath.Dir(path), ".aidr-managed-")
	if err != nil {
		return code("aidr_managed_write_failed")
	}
	defer os.Remove(file.Name())
	defer file.Close()
	if err = file.Chmod(mode); err != nil {
		return code("aidr_managed_write_failed")
	}
	if _, err = file.Write(data); err != nil {
		return code("aidr_managed_write_failed")
	}
	if err = file.Sync(); err != nil {
		return code("aidr_managed_write_failed")
	}
	if err = file.Close(); err != nil {
		return code("aidr_managed_write_failed")
	}
	if err = os.Rename(file.Name(), path); err != nil {
		return code("aidr_managed_write_failed")
	}
	directory, err := os.Open(filepath.Dir(path))
	if err != nil {
		return code("aidr_managed_write_failed")
	}
	defer directory.Close()
	if err = directory.Sync(); err != nil {
		return code("aidr_managed_write_failed")
	}
	return nil
}

func managedDigest(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

func copyManagedBinary(source, target string) error {
	in, err := os.Open(source)
	if err != nil {
		return code("aidr_desktop_binary_missing")
	}
	defer in.Close()
	info, err := in.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > (128<<20) {
		return code("aidr_managed_binary_invalid")
	}
	out, err := os.CreateTemp(filepath.Dir(target), ".aidr-binary-")
	if err != nil {
		return code("aidr_managed_write_failed")
	}
	defer os.Remove(out.Name())
	defer out.Close()
	if err = out.Chmod(0755); err != nil {
		return code("aidr_managed_write_failed")
	}
	if n, e := io.Copy(out, io.LimitReader(in, (128<<20)+1)); e != nil || n != info.Size() {
		return code("aidr_managed_binary_invalid")
	}
	if out.Sync() != nil || out.Close() != nil || os.Rename(out.Name(), target) != nil {
		return code("aidr_managed_write_failed")
	}
	return nil
}

func applyManagedAt(layout ManagedLayout, agent, action, self string, uid uint32, floor string) error {
	if agent != "codex" && agent != "claude" || action != "install" && action != "remove" {
		return code("aidr_managed_action_invalid")
	}
	if err := protectedManagedDir(layout.Root, floor, uid); err != nil {
		return err
	}
	if err := protectedManagedDir(filepath.Dir(layout.Config), floor, uid); err != nil {
		return err
	}
	fd, err := syscall.Open(filepath.Join(layout.Root, "install.lock"), syscall.O_CREAT|syscall.O_RDWR|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err != nil {
		return code("aidr_managed_action_busy")
	}
	lock := os.NewFile(uintptr(fd), "install.lock")
	defer lock.Close()
	info, err := lock.Stat()
	stat, ok := infoSys(info)
	if err != nil || !ok || !info.Mode().IsRegular() || stat.Uid != uid || info.Mode().Perm()&0077 != 0 {
		return code("aidr_managed_path_invalid")
	}
	if syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB) != nil {
		return code("aidr_managed_action_busy")
	}
	raw, mode, err := readManagedFile(layout.Config, uid, managedConfigLimit)
	if err != nil {
		return err
	}
	manifestPath := filepath.Join(layout.Root, agent+"-ownership.json")
	manifest, _, err := readManagedFile(manifestPath, uid, 16384)
	if err != nil {
		return err
	}
	owner := managedOwnership{Version: 1, Agent: agent, PluginVersion: BundledPluginVersion}
	if len(manifest) > 0 {
		decoder := json.NewDecoder(bytes.NewReader(manifest))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&owner) != nil || owner.Version != 1 || owner.Agent != agent || (owner.Phase != "ready" && owner.Phase != "prepared" && owner.Phase != "removed") {
			return code("aidr_managed_ownership_unknown")
		}
		if owner.Phase == "prepared" && managedDigest(raw) != owner.Before && managedDigest(raw) != owner.After {
			return code("aidr_managed_recovery_required")
		}
	}
	if action == "remove" && len(manifest) == 0 {
		return code("aidr_managed_ownership_unknown")
	}
	next, addedFeature, err := mergeManagedConfig(raw, agent, layout, action == "install", len(manifest) > 0)
	if err != nil {
		return err
	}
	if action == "remove" && agent == "codex" && owner.AddedFeature {
		var values map[string]any
		if _, err = toml.Decode(string(next), &values); err != nil {
			return code("aidr_managed_config_invalid")
		}
		if _, remaining := values["hooks"]; !remaining {
			features, _ := values["features"].(map[string]any)
			if features["hooks"] == true {
				delete(features, "hooks")
			}
			if len(features) == 0 {
				delete(values, "features")
			}
			var encoded bytes.Buffer
			if toml.NewEncoder(&encoded).Encode(values) != nil {
				return code("aidr_managed_config_invalid")
			}
			next = encoded.Bytes()
		}
	}
	if action == "install" && len(manifest) == 0 {
		owner.AddedFeature = addedFeature
	}
	// Two bounded backup files per host: initial evidence and latest preimage.
	if len(manifest) == 0 {
		if err = managedWrite(filepath.Join(layout.Root, agent+"-original"), raw, 0600); err != nil {
			return err
		}
	}
	if err = managedWrite(filepath.Join(layout.Root, agent+"-previous"), raw, 0600); err != nil {
		return err
	}
	owner.Before, owner.After, owner.Phase = managedDigest(raw), managedDigest(next), "prepared"
	owner.PluginVersion = BundledPluginVersion
	pending, _ := json.Marshal(owner)
	if err = managedWrite(manifestPath, pending, 0600); err != nil {
		return err
	}
	if action == "install" {
		if err = installManagedBinary(layout, self, uid); err != nil {
			return err
		}
	}
	// Another administrator may have changed the shared file while we were
	// preparing. Do not replace that change with our stale preimage.
	current, _, err := readManagedFile(layout.Config, uid, managedConfigLimit)
	if err != nil || !bytes.Equal(current, raw) {
		return code("aidr_managed_config_changed")
	}
	if err = managedWrite(layout.Config, next, mode); err != nil {
		return err
	}
	owner.Phase = "ready"
	if action == "remove" {
		owner.Phase = "removed"
	}
	finished, _ := json.Marshal(owner)
	return managedWrite(manifestPath, finished, 0600)
}

// A configured file is evidence of installation, not of host loading/trust.
func SystemManagedConfigured(agent string) (bool, error) {
	layout, err := SystemManagedLayout(agent)
	if err != nil {
		return false, err
	}
	raw, _, err := readManagedFile(layout.Config, 0, managedConfigLimit)
	if err != nil {
		return false, err
	}
	if !managedContains(raw, agent, layout) {
		return false, nil
	}
	info, err := os.Lstat(layout.Binary)
	stat, ok := infoSys(info)
	if err != nil || !ok || !info.Mode().IsRegular() || stat.Uid != 0 || info.Mode().Perm()&0022 != 0 || info.Mode().Perm()&0111 == 0 {
		return false, code("aidr_managed_binary_invalid")
	}
	return true, nil
}

// Version is observed from the protected installed executable's receipt and
// digest, rather than inferred from the package inspecting it.
func SystemManagedVersion(agent string) (string, error) {
	layout, err := SystemManagedLayout(agent)
	if err != nil {
		return "", err
	}
	return managedVersionAt(layout, 0)
}

func managedVersionAt(layout ManagedLayout, uid uint32) (string, error) {
	receipt, err := readManagedBinaryReceipt(layout, uid)
	if err != nil {
		return "", err
	}
	if receipt.Version == 0 || receipt.Phase != "ready" {
		return "", code("aidr_managed_recovery_required")
	}
	digest, err := managedBinaryDigest(layout.Binary, uid)
	if err != nil {
		return "", err
	}
	if digest != receipt.After {
		return "", code("aidr_managed_binary_invalid")
	}
	return receipt.PluginVersion, nil
}
