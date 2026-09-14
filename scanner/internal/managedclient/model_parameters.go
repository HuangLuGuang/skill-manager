package managedclient

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/BurntSushi/toml"
	"gopkg.in/yaml.v3"
)

func readNativeModelConfig(home, kind string) (map[string]any, error) {
	files := modelConfigFiles(kind)
	if len(files) == 0 {
		return nil, errors.New("model_config.agent_unsupported")
	}
	body, err := os.ReadFile(resolvedModelPath(home, kind, files[0]))
	if errors.Is(err, os.ErrNotExist) {
		return map[string]any{}, nil
	}
	if err != nil {
		return nil, err
	}
	root := map[string]any{}
	switch filepath.Ext(files[0]) {
	case ".toml":
		_, err = toml.Decode(string(body), &root)
	case ".yaml":
		err = yaml.Unmarshal(body, &root)
	default:
		err = decodeModelJSON(body, &root)
	}
	if err != nil || root == nil {
		return nil, errors.New("model_config.invalid_document")
	}
	return root, nil
}

func readModelParameters(home, kind string) (map[string]any, error) {
	root, err := readNativeModelConfig(home, kind)
	if err != nil {
		return nil, err
	}
	result := map[string]any{}
	for key, field := range modelAdapters[kind].Parameters {
		var value any = root
		for _, part := range strings.Split(field.Path, ".") {
			obj, ok := value.(map[string]any)
			if !ok {
				value = nil
				break
			}
			value = obj[part]
		}
		if kind == "claude-code" && field.Type == "integer" {
			if raw, ok := value.(string); ok {
				if n, err := strconv.Atoi(raw); err == nil {
					value = n
				}
			}
		}
		if value != nil {
			result[key] = value
		}
	}
	return result, nil
}

func writeModelParameters(home, kind string, parameters map[string]any) error {
	if err := ValidateModelParameters(kind, parameters); err != nil {
		return err
	}
	if len(parameters) == 0 {
		return nil
	}
	root, err := readNativeModelConfig(home, kind)
	if err != nil {
		return err
	}
	for key, value := range parameters {
		if value == nil {
			continue
		}
		field := modelAdapters[kind].Parameters[key]
		if field.Type == "integer" {
			// JSON task payloads decode numbers as float64; native TOML readers
			// distinguish 0 from 0.0 even when JSON readback compares equal.
			if number, ok := value.(float64); ok {
				value = int64(number)
			}
		}
		parts := strings.Split(field.Path, ".")
		current := root
		for _, part := range parts[:len(parts)-1] {
			current = objectConfig(current, part)
		}
		if kind == "claude-code" {
			encoded, _ := json.Marshal(value)
			value = string(encoded)
		}
		current[parts[len(parts)-1]] = value
	}
	path := resolvedModelPath(home, kind, modelConfigFiles(kind)[0])
	var body []byte
	switch filepath.Ext(path) {
	case ".toml":
		var buffer bytes.Buffer
		err = toml.NewEncoder(&buffer).Encode(root)
		body = buffer.Bytes()
	case ".yaml":
		body, err = yaml.Marshal(root)
	default:
		body, err = json.MarshalIndent(root, "", "  ")
	}
	if err != nil {
		return err
	}
	if err := atomicWriteFile(path, body, 0o600); err != nil {
		return err
	}
	actual, err := readModelParameters(home, kind)
	if err != nil {
		return err
	}
	for key, value := range parameters {
		if value == nil {
			continue
		}
		want, _ := json.Marshal(value)
		got, _ := json.Marshal(actual[key])
		if !bytes.Equal(want, got) {
			return errors.New("model_config.parameter_readback_failed")
		}
	}
	return nil
}
