package managedclient

import (
	"encoding/json"
	"fmt"
	"math"
	"regexp"
)

type ModelParameter struct {
	Type      string   `json:"type"`
	Min       float64  `json:"min"`
	Max       float64  `json:"max"`
	Enum      []string `json:"enum,omitempty"`
	Path      string   `json:"path"`
	Wire      string   `json:"wire"`
	Condition string   `json:"condition"`
}

type ModelAdapterSpec struct {
	ParameterVersions []string                  `json:"parameter_versions,omitempty"`
	ParameterStatus   string                    `json:"parameter_status,omitempty"`
	Verification      string                    `json:"verification,omitempty"`
	ConfigRootEnv     string                    `json:"config_root_env,omitempty"`
	ConfigRootPrefix  string                    `json:"config_root_prefix,omitempty"`
	ConfigFileEnv     string                    `json:"config_file_env,omitempty"`
	Label             string                    `json:"label"`
	Protocol          string                    `json:"protocol"`
	Files             []string                  `json:"files"`
	FilesByOS         map[string][]string       `json:"files_by_os,omitempty"`
	Platforms         []string                  `json:"platforms,omitempty"`
	Binary            string                    `json:"binary"`
	Source            string                    `json:"source"`
	Parameters        map[string]ModelParameter `json:"parameters"`
}

var modelAdapters = func() map[string]ModelAdapterSpec {
	var contract struct {
		Agents map[string]ModelAdapterSpec `json:"agents"`
	}
	if err := json.Unmarshal([]byte(modelContractJSON), &contract); err != nil {
		panic(err)
	}
	return contract.Agents
}()

var modelSemanticVersion = regexp.MustCompile(`\b[vV]?([0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.]+)?)`)

func modelContractForVersion(kind, version string) ModelAdapterSpec {
	spec := modelAdapters[kind]
	match := modelSemanticVersion.FindStringSubmatch(version)
	supported := false
	if len(match) == 2 {
		for _, candidate := range spec.ParameterVersions {
			supported = supported || candidate == match[1]
		}
	}
	spec.ParameterStatus = "available"
	if !supported && len(spec.Parameters) > 0 {
		spec.ParameterStatus = "version_unverified"
		spec.Parameters = map[string]ModelParameter{}
	}
	return spec
}

func validateModelParameterVersion(kind, version string, parameters map[string]any) error {
	for _, value := range parameters {
		if value != nil && modelContractForVersion(kind, version).ParameterStatus != "available" {
			return fmt.Errorf("model_config.parameter_version_unverified")
		}
	}
	return nil
}

func ValidateModelParameters(agentType string, parameters map[string]any) error {
	spec, ok := modelAdapters[agentType]
	if !ok {
		return fmt.Errorf("model_config.agent_unsupported")
	}
	for key, value := range parameters {
		field, ok := spec.Parameters[key]
		if !ok {
			return fmt.Errorf("model_config.parameter_unsupported: %s", key)
		}
		if value == nil {
			continue
		} // Unset means retain the native value.
		if field.Type == "integer" || field.Type == "number" {
			encoded, err := json.Marshal(value)
			if err != nil {
				return fmt.Errorf("model_config.parameter_invalid: %s", key)
			}
			var number float64
			if json.Unmarshal(encoded, &number) != nil || number < field.Min || number > field.Max || (field.Type == "integer" && math.Trunc(number) != number) {
				return fmt.Errorf("model_config.parameter_invalid: %s", key)
			}
		} else {
			text, ok := value.(string)
			if !ok {
				return fmt.Errorf("model_config.parameter_invalid: %s", key)
			}
			found := false
			for _, option := range field.Enum {
				if text == option {
					found = true
				}
			}
			if !found {
				return fmt.Errorf("model_config.parameter_invalid: %s", key)
			}
		}
	}
	return nil
}
