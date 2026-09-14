package managedclient

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestModelParametersRequireVerifiedNativeVersion(t *testing.T) {
	for _, version := range []string{"", "0.131.0", "0.132.0-beta.1", "0.133.0"} {
		spec := modelContractForVersion("codex", version)
		if len(spec.Parameters) != 0 || spec.ParameterStatus != "version_unverified" {
			t.Fatalf("unverified version exposed editable parameters: %q", version)
		}
		if validateModelParameterVersion("codex", version, map[string]any{"request_max_retries": 0}) == nil {
			t.Fatal("unverified version accepted explicit parameter")
		}
		if err := validateModelParameterVersion("codex", version, map[string]any{"request_max_retries": nil}); err != nil {
			t.Fatal("unset parameter should preserve configuration")
		}
	}
	if len(modelContractForVersion("codex", "codex-cli 0.132.0").Parameters) == 0 {
		t.Fatal("version filtering changed the shared contract")
	}
	if err := validateModelParameterVersion("codex", "v0.132.0", map[string]any{"request_max_retries": 0}); err != nil {
		t.Fatal(err)
	}
}

func TestJSONTaskIntegersRemainNativeIntegers(t *testing.T) {
	var parameters map[string]any
	if err := json.Unmarshal([]byte(`{"request_max_retries":0,"stream_idle_timeout_ms":1500}`), &parameters); err != nil {
		t.Fatal(err)
	}
	home := t.TempDir()
	if _, err := ApplyModelConfigRevision(home, "https://gateway.example", "codex", "codex", "model", "key", "", parameters); err != nil {
		t.Fatal(err)
	}
	actual, err := readModelParameters(home, "codex")
	if err != nil {
		t.Fatal(err)
	}
	for key := range parameters {
		if _, ok := actual[key].(int64); !ok {
			t.Fatalf("%s has noninteger TOML type %T", key, actual[key])
		}
	}
}

func TestModelParameterValidationAndReadback(t *testing.T) {
	for kind, parameters := range map[string]map[string]any{
		"claude-code": {"timeout_ms": 1000, "max_output_tokens": 512},
		"codex":       {"stream_idle_timeout_ms": 1000, "request_max_retries": 0},
		"hermes":      {"max_tokens": 512},
	} {
		t.Run(kind, func(t *testing.T) {
			home := t.TempDir()
			if _, err := ApplyModelConfigRevision(home, "https://gateway.example", kind, kind, "model-a", "key", "", parameters); err != nil {
				t.Fatal(err)
			}
			if err := ApplyModelConfig(home, "https://gateway.example", kind, kind, "model-b", "key"); err != nil {
				t.Fatal(err)
			}
			actual, err := readModelParameters(home, kind)
			if err != nil || len(actual) != len(parameters) {
				t.Fatalf("lost parameters: %v, %v", actual, err)
			}
			if err := ValidateModelParameters(kind, actual); err != nil {
				t.Fatal(err)
			}
		})
	}
	for _, parameters := range []map[string]any{{"temperature": 0.5}, {"timeout_ms": true}, {"timeout_ms": 1000.1}, {"timeout_ms": "1000"}} {
		if err := ValidateModelParameters("claude-code", parameters); err == nil {
			t.Fatal("accepted invalid parameter")
		}
	}
}

func TestCodexNoncanonicalTOMLPreservesProviderOptions(t *testing.T) {
	home := t.TempDir()
	body := []byte("model='old'\nmodel_provider='old'\n[model_providers.\"agent_manager\"] # comment\nrequest_max_retries=7\n[features] # comment\nshell_tool=true\n")
	path := filepath.Join(home, ".codex", "config.toml")
	if err := atomicWriteFile(path, body, 0o600); err != nil {
		t.Fatal(err)
	}
	change, err := ApplyModelConfigRevision(home, "https://gateway.example", "codex", "codex", "new", "key", "")
	if err != nil {
		t.Fatal(err)
	}
	parameters, err := readModelParameters(home, "codex")
	if err != nil || parameters["request_max_retries"] != int64(7) {
		t.Fatalf("provider options lost: %v %v", parameters, err)
	}
	if err := RestoreModelConfig(home, change.ID); err != nil {
		t.Fatal(err)
	}
	restored, _ := os.ReadFile(path)
	if string(restored) != string(body) {
		t.Fatal("restore did not preserve original TOML")
	}
	state := InspectModelConfig(home, "codex")
	if state.AppliedRevision != state.Revision || state.CanRestore || state.Status != "restored" {
		t.Fatalf("restoration must expose the restored revision for verification: %+v", state)
	}
}
