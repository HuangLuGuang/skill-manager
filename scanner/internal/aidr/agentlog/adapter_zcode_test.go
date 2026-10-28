package agentlog

import (
	"encoding/json"
	"os"
	"testing"
)

func TestZcodeCapturedNativeParts(t *testing.T) {
	raw, err := os.ReadFile("testdata/zcode-3.16.3/native-parts.json")
	if err != nil {
		t.Fatal(err)
	}
	var rows []sqlitePartRecord
	if json.Unmarshal(raw, &rows) != nil {
		t.Fatal("invalid fixture")
	}
	calls := map[string]bool{}
	for _, row := range rows {
		drafts, err := parseZcode(row)
		if err != nil {
			t.Fatal(row.ID, err)
		}
		for _, d := range drafts {
			if d.Kind == "tool_call" {
				calls[d.Tool] = true
				if d.Turn == "" {
					t.Fatal("native turn lost", row.ID)
				}
			}
		}
	}
	for _, tool := range []string{"Bash", "Write", "Skill", "mcp__aidr_probe__ping"} {
		if !calls[tool] {
			t.Fatal("missing native fixture", tool)
		}
	}
}

func TestZcodeMutableSQLiteAndReadOnly(t *testing.T) { testMutableSQLiteParts(t, "zcode", "db.sqlite") }

func TestZcodeNativeToolCallMessagePhase(t *testing.T) {
	r := sqlitePartRecord{ID: "p", Session: "s", Created: 1793166503300, Message: json.RawMessage(`{"role":"assistant","finish":"tool-calls","time":{"completed":1793166503301}}`), Part: json.RawMessage(`{"type":"text","text":"calling tool"}`)}
	drafts, err := parseZcode(r)
	if err != nil || len(drafts) != 1 || drafts[0].MessagePhase != "commentary" {
		t.Fatal(drafts, err)
	}
}

func TestZcodeNativeAnchorAndHiddenMessages(t *testing.T) {
	r := sqlitePartRecord{ID: "p", Session: "s", Created: 1793166503300, Message: json.RawMessage(`{"role":"user","modelSelection":{"modelId":"GLM-5.3","providerId":"test-provider"},"anchor":{"turnId":"native-turn"}}`), Part: json.RawMessage(`{"type":"text","text":"test-only"}`)}
	drafts, err := parseZcode(r)
	if err != nil || len(drafts) != 1 || drafts[0].Turn != "native-turn" || drafts[0].ModelContext.Model != "GLM-5.3" {
		t.Fatal(drafts, err)
	}
	r.Message = json.RawMessage(`{"role":"user","synthetic":true,"anchor":{"turnId":"native-turn"}}`)
	drafts, err = parseZcode(r)
	if err != nil || len(drafts) != 0 {
		t.Fatal("synthetic runtime context collected", err)
	}
	r.Message = json.RawMessage(`{"role":"user"}`)
	drafts, err = parseZcode(r)
	if err != nil || len(drafts) != 1 || drafts[0].Turn != "" || drafts[0].ModelContext != nil {
		t.Fatal("missing native fields were inferred", err)
	}
}
