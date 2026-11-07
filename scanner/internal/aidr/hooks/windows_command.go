package hooks

import (
	"encoding/base64"
	"encoding/binary"
	"strings"
	"unicode/utf16"
)

// cmd hosts need an encoded script; PowerShell hosts run windowsHookScript directly.
func windowsHookCommand(executable string, args []string) string {
	return windowsEncodedCommand(windowsHookScript(executable, args))
}

func windowsEncodedCommand(command string) string {
	encoded := utf16.Encode([]rune(command))
	data := make([]byte, len(encoded)*2)
	for i, value := range encoded {
		binary.LittleEndian.PutUint16(data[i*2:], value)
	}
	return "powershell.exe -NoLogo -NoProfile -NonInteractive -InputFormat Text -OutputFormat Text -EncodedCommand " + base64.StdEncoding.EncodeToString(data)
}

func windowsHookScript(executable string, args []string) string {
	quote := func(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }
	command := "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $OutputEncoding=[Console]::InputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); try { [Console]::In.ReadToEnd() | & " + quote(executable)
	for _, arg := range args {
		command += " " + quote(arg)
	}
	command += "; exit $LASTEXITCODE } catch { "
	for i, arg := range args {
		if arg == "--event" && i+1 < len(args) && args[i+1] == "PreToolUse" {
			return command + `[Console]::Out.WriteLine('{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"aidr_hook_binary_unavailable"}}'); exit 0 }`
		}
	}
	command += "[Console]::Error.WriteLine('aidr_hook_binary_unavailable'); exit 1 }"
	return command
}

// Let PowerShell own the response pipe until the native bridge exits.
func windowsCapturedHookScript(executable string, args []string) string {
	script := windowsHookScript(executable, args)
	script = strings.Replace(script, "try { [Console]::In.ReadToEnd()", "try { $response = [Console]::In.ReadToEnd()", 1)
	return strings.Replace(script, "; exit $LASTEXITCODE", "; $bridgeExit = $LASTEXITCODE; [Console]::Out.WriteLine(($response -join [Environment]::NewLine)); exit $bridgeExit", 1)
}
