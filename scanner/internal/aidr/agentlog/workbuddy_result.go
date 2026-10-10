package agentlog

import "encoding/json"

// WorkBuddy desktop 5.6.2: Bash/PowerShell produce rawResponse.exitCode;
// tool execution and MCP adapters expose explicit is_error/isError flags.
// Logs persist rawResponse under providerData.toolResult; Hooks send it directly.
func projectWorkBuddyResult(b *Behavior, tool string, raw json.RawMessage) {
	b.Status, b.ExitCode = "unknown", nil
	b.Basis, b.Uncertainty = []string{}, []string{}
	var obj map[string]json.RawMessage
	if json.Unmarshal(raw, &obj) != nil || obj == nil {
		b.Uncertainty = append(b.Uncertainty, "host_result_not_provided")
		return
	}
	invalid, conflict, cancelled := false, false, false
	var failure *bool
	for _, key := range []string{"is_error", "isError", "interrupted", "sandboxDenied"} {
		value, exists := obj[key]
		if !exists {
			continue
		}
		var flag bool
		if string(value) == "null" || json.Unmarshal(value, &flag) != nil {
			invalid = true
			continue
		}
		switch key {
		case "interrupted":
			cancelled = flag
		case "sandboxDenied":
			if flag {
				b.Status = "reported_error"
				b.Basis = append(b.Basis, "is_error_true")
			}
		default:
			if failure != nil && *failure != flag {
				conflict = true
			}
			v := flag
			failure = &v
		}
	}
	if failure != nil {
		if *failure {
			b.Status = "reported_error"
			if len(b.Basis) == 0 {
				b.Basis = append(b.Basis, "is_error_true")
			}
		} else if b.Status == "reported_error" {
			conflict = true
		} else {
			b.Status = "reported_complete"
			b.Basis = append(b.Basis, "is_error_false")
		}
	}
	if tool == "Bash" || tool == "PowerShell" {
		if value, exists := obj["exitCode"]; exists && string(value) != "null" {
			var code int
			if json.Unmarshal(value, &code) != nil || code < -2147483648 || code > 2147483647 {
				invalid = true
			} else {
				if (b.Status == "reported_error" && code == 0) || (failure != nil && !*failure && code != 0) {
					conflict = true
				}
				b.ExitCode = &code
				b.Basis = append(b.Basis, "structured_exit_code")
				if code == 0 {
					b.Status = "reported_success"
				} else {
					b.Status = "reported_error"
				}
			}
		}
	}
	if cancelled {
		b.Status = "reported_cancelled"
		b.Basis = append(b.Basis, "interrupted")
	}
	if invalid || conflict {
		b.Status, b.ExitCode = "unknown", nil
		reason := "result_format_unsupported"
		if conflict {
			reason = "result_fields_conflict"
		}
		b.Uncertainty = append(b.Uncertainty, reason)
	} else if len(b.Basis) == 0 {
		b.Uncertainty = append(b.Uncertainty, "host_result_not_provided")
	}
}
