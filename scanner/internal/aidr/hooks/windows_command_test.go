package hooks

import (
	"encoding/base64"
	"encoding/binary"
	"strings"
	"testing"
	"unicode/utf16"
)

func TestWindowsHookCommandQuotesLiteralPaths(t *testing.T) {
	command := windowsHookCommand(`C:\客户's & $data\bridge.exe`, []string{"aidr-hook", `C:\用户's\config.json`})
	data, err := base64.StdEncoding.DecodeString(command[strings.LastIndex(command, " ")+1:])
	if err != nil {
		t.Fatal(err)
	}
	units := make([]uint16, len(data)/2)
	for i := range units {
		units[i] = binary.LittleEndian.Uint16(data[i*2:])
	}
	script := string(utf16.Decode(units))
	if !strings.Contains(script, `'C:\客户''s & $data\bridge.exe' 'aidr-hook' 'C:\用户''s\config.json'`) || !strings.Contains(script, "exit $LASTEXITCODE") {
		t.Fatal(script)
	}
}
