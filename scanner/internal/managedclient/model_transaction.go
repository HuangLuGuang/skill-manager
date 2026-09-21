package managedclient

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// A revision covers every file an adapter owns, including absence. It is safe
// to send to the platform; configuration bytes and credentials stay local.
type modelFile struct {
	Target    string      `json:"target"`
	Path      string      `json:"path"`
	Before    []byte      `json:"before"`
	Existed   bool        `json:"existed"`
	Mode      os.FileMode `json:"mode"`
	AfterHash string      `json:"after_hash"`
}

type ModelChange struct {
	Restored         bool                   `json:"restored,omitempty"`
	AppliedRevision  string                 `json:"applied_revision,omitempty"`
	Evidence         []ModelRequestEvidence `json:"evidence,omitempty"`
	Error            string                 `json:"error,omitempty"`
	ID               string                 `json:"id"`
	AgentType        string                 `json:"agent_type"`
	Model            string                 `json:"model"`
	GatewaySource    string                 `json:"gateway_source,omitempty"`
	CredentialSource string                 `json:"credential_source,omitempty"`
	VerificationMode string                 `json:"verification_mode,omitempty"`
	Status           string                 `json:"status"`
	Revision         string                 `json:"revision"`
	Files            []modelFile            `json:"files"`
}

func modelConfigFiles(agentType string) []string {
	spec := modelAdapters[agentType]
	if len(spec.Platforms) > 0 {
		found := false
		for _, platform := range spec.Platforms {
			if platform == runtime.GOOS {
				found = true
			}
		}
		if !found {
			return nil
		}
	}
	if paths := spec.FilesByOS[runtime.GOOS]; len(paths) > 0 {
		return paths
	}
	return spec.Files
}

func configHash(body []byte, exists bool) string {
	h := sha256.New()
	if exists {
		h.Write([]byte{1})
	} else {
		h.Write([]byte{0})
	}
	h.Write(body)
	return hex.EncodeToString(h.Sum(nil))
}

func readModelFiles(home, agentType string) ([]modelFile, string, error) {
	paths := modelConfigFiles(agentType)
	if len(paths) == 0 {
		return nil, "", errors.New("model_config.agent_unsupported")
	}
	files := make([]modelFile, 0, len(paths))
	h := sha256.New()
	for _, path := range paths {
		full := resolvedModelPath(home, agentType, path)
		if agentType == "opencode" && filepath.Base(full) == "opencode.json" {
			if _, err := os.Stat(full); err == nil {
				if _, err := os.Stat(full + "c"); err == nil {
					return nil, "", errors.New("model_config.ambiguous_paths")
				}
			}
		}
		if !filepath.IsAbs(full) {
			return nil, "", errors.New("model_config.path_invalid")
		}
		// Following a link would make the preview's target differ from the write.
		for parent := full; ; parent = filepath.Dir(parent) {
			info, err := os.Lstat(parent)
			if err == nil && info.Mode()&os.ModeSymlink != 0 {
				return nil, "", errors.New("model_config.symlink")
			}
			if err != nil && !errors.Is(err, os.ErrNotExist) {
				return nil, "", err
			}

			if parent == filepath.Dir(parent) {
				break
			}
		}
		body, err := os.ReadFile(full)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return nil, "", err
		}
		f := modelFile{Path: path, Target: full, Before: body, Existed: err == nil, Mode: 0o600}
		if info, err := os.Stat(full); err == nil {
			f.Mode = info.Mode().Perm()
		}
		h.Write([]byte(full + "\x00" + configHash(body, f.Existed)))
		files = append(files, f)
	}
	return files, hex.EncodeToString(h.Sum(nil)), nil
}

func ModelConfigRevision(home, agentType string) (string, error) {
	_, revision, err := readModelFiles(home, agentType)
	return revision, err
}

func lockModelConfig(home, agentType string) (func(), error) {
	if len(modelConfigFiles(agentType)) == 0 {
		return nil, errors.New("model_config.agent_unsupported")
	}
	dir := filepath.Join(home, ".agent-manager", "model-locks")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, agentType)
	return lockModelFile(path)
}

func ApplyModelConfig(home, server, localAgentID, agentType, model, credential string) error {
	_, err := ApplyModelConfigRevision(home, server, localAgentID, agentType, model, credential, "")
	return err
}

// Stage and validate all files before touching live configuration. The journal
// is private and retains original bytes so recovery does not reserialize them.
func ApplyModelConfigRevision(home, server, localAgentID, agentType, model, credential, expected string, options ...map[string]any) (ModelChange, error) {
	change := ModelChange{AgentType: agentType, Model: model}
	parameters := map[string]any{}
	if len(options) > 0 {
		parameters = options[0]
	}
	if len(options) > 1 {
		change.GatewaySource = strings.TrimSpace(stringValue(options[1], "gateway_source"))
		change.CredentialSource = strings.TrimSpace(stringValue(options[1], "credential_source"))
		change.VerificationMode = strings.TrimSpace(stringValue(options[1], "verification_mode"))
	}
	if err := ValidateModelParameters(agentType, parameters); err != nil {
		return change, err
	}
	unlock, err := lockModelConfig(home, agentType)
	if err != nil {
		return change, err
	}
	defer unlock()
	files, revision, err := readModelFiles(home, agentType)
	if err != nil {
		return change, err
	}
	if expected != "" && expected != revision {
		return change, errors.New("model_config.conflict")
	}
	stage, err := os.MkdirTemp("", "agent-manager-model-stage-")
	if err != nil {
		return change, err
	}
	defer os.RemoveAll(stage)
	for _, f := range files {
		if f.Existed {
			if err := atomicWriteFile(filepath.Join(stage, f.Path), f.Before, f.Mode); err != nil {
				return change, err
			}
		}
	}
	if err := renderModelConfig(stage, server, localAgentID, agentType, model, credential); err != nil {
		return change, err
	}
	if err := writeModelParameters(stage, agentType, parameters); err != nil {
		return change, err
	}
	state := InspectModelConfig(stage, agentType)
	if state.Error != "" || state.Model != model {
		return change, errors.New("model_config.readback_failed")
	}
	updated := make([][]byte, len(files))
	for i := range files {
		updated[i], err = os.ReadFile(filepath.Join(stage, files[i].Path))
		if errors.Is(err, os.ErrNotExist) && !files[i].Existed {
			updated[i] = nil
			err = nil
		}
		if err != nil {
			return change, err
		}
		files[i].AfterHash = configHash(updated[i], updated[i] != nil)
	}
	_, current, err := readModelFiles(home, agentType)
	if err != nil {
		return change, err
	}
	if current != revision {
		return change, errors.New("model_config.conflict")
	}
	change.ID = time.Now().UTC().Format("20060102T150405.000000000Z")
	change.Revision, change.Files, change.Status = revision, files, "applying"
	journal := filepath.Join(home, ".agent-manager", "model-changes", change.ID+".json")
	if err := saveModelChange(journal, change); err != nil {
		return change, err
	}
	defer func() {
		if change.Status == "applying" {
			change.Status = "failed"
			_ = saveModelChange(journal, change)
		}
	}()
	for i, f := range files {
		if bytes.Equal(updated[i], f.Before) && f.Existed == (updated[i] != nil) {
			continue
		}
		// Recheck immediately before each rename; cooperating sidecars hold the lock.
		body, readErr := os.ReadFile(f.Target)
		if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
			return change, readErr
		}
		if configHash(body, readErr == nil) != configHash(f.Before, f.Existed) {
			return change, errors.New("model_config.conflict")
		}
		if f.Existed {
			if err := backupAgentConfig(home, localAgentID, filepath.Base(f.Path), f.Before); err != nil {
				return change, err
			}
		}
		if err := atomicWriteFile(f.Target, updated[i], 0o600); err != nil {
			change.Status = "failed"
			_ = saveModelChange(journal, change)
			return change, fmt.Errorf("model_config.write_failed (recovery %s): %w", change.ID, err)
		}
	}
	for _, f := range files {
		body, err := os.ReadFile(f.Target)
		if err != nil && !errors.Is(err, os.ErrNotExist) {
			return change, err
		}
		if configHash(body, err == nil) != f.AfterHash {
			return change, errors.New("model_config.readback_failed")
		}
	}
	change.AppliedRevision, err = ModelConfigRevision(home, agentType)
	if err != nil {
		return change, err
	}
	change.Status = "pending_restart"
	return change, saveModelChange(journal, change)
}

func saveModelChange(path string, change ModelChange) error {
	body, err := json.Marshal(change)
	if err != nil {
		return err
	}
	return atomicWriteFile(path, body, 0o600)
}

func attachModelChangeState(home, kind string, state *ModelConfigState) {
	dir := filepath.Join(home, ".agent-manager", "model-changes")
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	for i := len(entries) - 1; i >= 0; i-- {
		if entries[i].IsDir() {
			continue
		}
		body, err := os.ReadFile(filepath.Join(dir, entries[i].Name()))
		if err != nil {
			continue
		}
		var change ModelChange
		if json.Unmarshal(body, &change) != nil || change.AgentType != kind {
			continue
		}
		state.ChangeID, state.Status = change.ID, change.Status
		state.GatewaySource = change.GatewaySource
		state.CredentialSource = change.CredentialSource
		state.VerificationMode = change.VerificationMode
		state.Verification = change.Evidence
		state.AppliedRevision = change.AppliedRevision
		if change.Status == "verified" && state.Revision != change.AppliedRevision {
			state.Status = "failed"
			state.Error = "model_config.conflict"
			state.Verification = nil
		}
		if state.Error == "" {
			state.Error = change.Error
		}
		current, _, err := readModelFiles(home, kind)
		state.CanRestore = err == nil && len(current) == len(change.Files) && !change.Restored && change.Status != "restored"
		if state.CanRestore {
			for index, file := range current {
				if file.Target != change.Files[index].Target || file.Path != change.Files[index].Path || (configHash(file.Before, file.Existed) != change.Files[index].AfterHash && configHash(file.Before, file.Existed) != configHash(change.Files[index].Before, change.Files[index].Existed)) {
					state.CanRestore = false
					break
				}
			}
		}
		return
	}
}

// Restore only files still equal to this change's output (or original bytes
// after a partial write). A later user edit is never overwritten.
func RestoreModelConfig(home, id string) error {
	if filepath.Base(id) != id || id == "." || id == "" {
		return errors.New("model_config.change_invalid")
	}
	path := filepath.Join(home, ".agent-manager", "model-changes", id+".json")
	body, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var change ModelChange
	if err := json.Unmarshal(body, &change); err != nil {
		return err
	}
	unlock, err := lockModelConfig(home, change.AgentType)
	if err != nil {
		return err
	}
	defer unlock()
	current, _, err := readModelFiles(home, change.AgentType)
	if err != nil {
		return err
	}
	if len(current) != len(change.Files) {
		return errors.New("model_config.change_invalid")
	}
	for i, f := range current {
		previous := change.Files[i]
		if f.Path != previous.Path || f.Target != previous.Target {
			return errors.New("model_config.change_invalid")
		}
		hash := configHash(f.Before, f.Existed)
		if hash != previous.AfterHash && hash != configHash(previous.Before, previous.Existed) {
			return errors.New("model_config.restore_conflict")
		}
	}
	for _, f := range change.Files {
		body, readErr := os.ReadFile(f.Target)
		if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
			return readErr
		}
		hash := configHash(body, readErr == nil)
		if hash != f.AfterHash && hash != configHash(f.Before, f.Existed) {
			return errors.New("model_config.restore_conflict")
		}
		if f.Existed {
			err = atomicWriteFile(f.Target, f.Before, f.Mode)
		} else {
			err = os.Remove(f.Target)
			if errors.Is(err, os.ErrNotExist) {
				err = nil
			}
		}
		if err != nil {
			return err
		}
	}
	restored, revision, err := readModelFiles(home, change.AgentType)
	if err != nil {
		return err
	}
	for i, file := range restored {
		expected := change.Files[i]
		if configHash(file.Before, file.Existed) != configHash(expected.Before, expected.Existed) {
			return errors.New("model_config.readback_failed")
		}
	}
	change.Status = "restored"
	change.Restored = true
	change.AppliedRevision = revision
	change.Evidence, change.Error = nil, ""
	return saveModelChange(path, change)
}
