package hooks

import (
	"bytes"
	"encoding/json"
	"io"

	"skill-manager/scanner/internal/aidr/agentlog"
)

type teleAgentReview struct {
	Session  string `json:"root_id"`
	Call     string `json:"caller_id"`
	Caller   string `json:"caller_type"`
	DataType string `json:"data_type"`
	Data     string `json:"data"`
	Extra    struct {
		Tool struct {
			ID string `json:"tool_id"`
		} `json:"tool_info"`
		MCP struct {
			Server string `json:"mcp_server"`
			Tool   string `json:"mcp_tool"`
		} `json:"mcp_info"`
	} `json:"extra"`
}

func decodeTeleAgentReview(raw []byte) (teleAgentReview, error) {
	var r teleAgentReview
	if len(raw) > MaxRecordBytes {
		return r, code("aidr_hook_record_oversized")
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	var extra any
	if d.Decode(&r) != nil || d.Decode(&extra) != io.EOF {
		return r, code("aidr_hook_record_invalid")
	}
	return r, nil
}

func teleAgentEvent(r teleAgentReview) (string, error) {
	prefix := ""
	switch r.Caller {
	case "tool":
		prefix = "Tool"
	case "mcp":
		prefix = "MCP"
	default:
		return "", code("aidr_hook_event_unsupported")
	}
	switch r.DataType {
	case "input":
		return "Before" + prefix + "Execute", nil
	case "output":
		return "After" + prefix + "Execute", nil
	default:
		return "", code("aidr_hook_event_unsupported")
	}
}

func TeleAgentEvent(raw []byte) (string, error) {
	r, err := decodeTeleAgentReview(raw)
	if err != nil {
		return "", err
	}
	return teleAgentEvent(r)
}

func teleAgentHookAdapter() hookAdapter {
	return hookAdapter{Desktop: teleAgentDesktopAdapter(), Decode: func(hook string, raw []byte) (input, error) {
		r, err := decodeTeleAgentReview(raw)
		if err != nil {
			return input{}, err
		}
		event, err := teleAgentEvent(r)
		if err != nil || event != hook {
			return input{}, code("aidr_hook_event_unsupported")
		}
		// Native worktree is a project root, not the session/tool working directory.
		in := input{Event: hook, Session: r.Session, Call: r.Call, Tool: r.Extra.Tool.ID}
		// sub_agent is a role name; message_id is not a native turn ID.
		if r.Caller == "mcp" {
			if !validID(r.Extra.MCP.Server, true) || !validID(r.Extra.MCP.Tool, true) {
				return in, code("aidr_hook_identity_invalid")
			}
			in.Tool = "mcp__" + r.Extra.MCP.Server + "__" + r.Extra.MCP.Tool
		}
		if r.DataType == "input" {
			if !json.Valid([]byte(r.Data)) {
				return in, code("aidr_hook_record_invalid")
			}
			in.Input = json.RawMessage(r.Data)
			in.ProjectionInput = agentlog.NormalizeTeleAgentInput(in.Input)
		} else {
			// Output body is text evidence, not a trusted exit/status envelope.
			in.Response, _ = json.Marshal(r.Data)
		}
		return validateCommandHook(in)
	}, WriteDecision: func(out io.Writer, hook, decision, reason string) error {
		result := 2
		if decision == "allow" {
			result = 1
		}
		return json.NewEncoder(out).Encode(map[string]any{"data": map[string]any{"result": result, "reason": reason}})
	}}
}
