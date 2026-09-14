package managedclient

import (
	"bytes"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Normalize JSONC and the JSON5 forms used by native Agent configuration.
// Non-JSON values (NaN/Infinity) fail rather than changing unrelated values.
func decodeModelJSON(body []byte, target *map[string]any) error {
	if !utf8.Valid(body) {
		return errors.New("model_config.invalid_json")
	}
	var tokens []string
	for i := 0; i < len(body); {
		c := body[i]
		if strings.ContainsRune(" \r\n\t", rune(c)) {
			i++
			continue
		}
		if c == '/' && i+1 < len(body) && body[i+1] == '/' {
			i += 2
			for i < len(body) && body[i] != '\n' {
				i++
			}
			continue
		}
		if c == '/' && i+1 < len(body) && body[i+1] == '*' {
			end := bytes.Index(body[i+2:], []byte("*/"))
			if end < 0 {
				return errors.New("model_config.invalid_json")
			}
			i += end + 4
			continue
		}
		if c == '"' || c == '\'' {
			quote := c
			i++
			var normalized strings.Builder
			normalized.WriteByte('"')
			closed := false
			for i < len(body) {
				c = body[i]
				i++
				if c == quote {
					closed = true
					break
				}
				if c == '\n' || c == '\r' {
					return errors.New("model_config.invalid_json")
				}
				if c == '\\' {
					if i >= len(body) {
						return errors.New("model_config.invalid_json")
					}
					escaped := body[i]
					i++
					switch escaped {
					case '\n':
						continue
					case '\r':
						if i < len(body) && body[i] == '\n' {
							i++
						}
						continue
					case '\'':
						normalized.WriteByte('\'')
					case 'x':
						if i+2 > len(body) {
							return errors.New("model_config.invalid_json")
						}
						normalized.WriteString("\\u00")
						normalized.Write(body[i : i+2])
						i += 2
					default:
						normalized.WriteByte('\\')
						normalized.WriteByte(escaped)
					}
				} else if c == '"' {
					normalized.WriteString(`\"`)
				} else {
					normalized.WriteByte(c)
				}
			}
			if !closed {
				return errors.New("model_config.invalid_json")
			}
			normalized.WriteByte('"')
			tokens = append(tokens, normalized.String())
			continue
		}
		if strings.ContainsRune("{}[]:,", rune(c)) {
			tokens = append(tokens, string(c))
			i++
			continue
		}
		start := i
		for i < len(body) && !strings.ContainsRune(" \r\n\t{}[]:,/", rune(body[i])) {
			i++
		}
		if i == start {
			return errors.New("model_config.invalid_json")
		}
		tokens = append(tokens, string(body[start:i]))
	}
	var result strings.Builder
	for i, token := range tokens {
		if token == "," && i+1 < len(tokens) && (tokens[i+1] == "}" || tokens[i+1] == "]") {
			continue
		}
		if i+1 < len(tokens) && tokens[i+1] == ":" && !strings.HasPrefix(token, `"`) {
			quoted, _ := json.Marshal(token)
			token = string(quoted)
		}
		if token != "" && (token[0] == '+' || token[0] == '.' || token[0] == '-' || (token[0] >= '0' && token[0] <= '9')) {
			if strings.Contains(strings.ToLower(token), "0x") {
				n, err := strconv.ParseInt(strings.TrimPrefix(token, "+"), 0, 64)
				if err != nil {
					return errors.New("model_config.invalid_json")
				}
				token = strconv.FormatInt(n, 10)
			} else if strings.HasPrefix(token, "+") || strings.HasPrefix(token, ".") || strings.HasPrefix(token, "-.") || strings.HasSuffix(token, ".") {
				n, err := strconv.ParseFloat(token, 64)
				if err != nil {
					return errors.New("model_config.invalid_json")
				}
				value, err := json.Marshal(n)
				if err != nil {
					return err
				}
				token = string(value)
			}
		}
		result.WriteString(token)
		result.WriteByte(' ')
	}
	if err := json.Unmarshal([]byte(result.String()), target); err != nil || *target == nil {
		return errors.New("model_config.invalid_json")
	}
	return nil
}
