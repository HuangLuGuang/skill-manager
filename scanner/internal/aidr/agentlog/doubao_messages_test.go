package agentlog

import (
	"context"
	"encoding/json"
	"testing"
)

func TestDoubaoClosedExchanges(t *testing.T) {
	row := func(v any) string { b, _ := json.Marshal(v); return string(b) + "\n" }
	user := row(map[string]any{"role": "user", "content": "same question"})
	call := func(id string) string {
		return row(map[string]any{"role": "assistant", "content": "working", "tool_calls": []any{map[string]any{"id": id}}})
	}
	result := func(id string) string {
		return row(map[string]any{"role": "tool", "tool_call_id": id, "content": "same result"})
	}
	final := row(map[string]any{"role": "assistant", "content": "same answer"})
	for _, tc := range []struct {
		name, raw string
		turns     map[string]string
		want      int
	}{
		{"two rounds", user + call("a") + result("a") + final + user + call("b") + result("b") + final, map[string]string{"a": "101", "b": "102"}, 6},
		{"initial prompt absent", call("a") + result("a") + final, map[string]string{"a": "101"}, 2},
		{"unknown call", user + call("a") + result("a") + final, nil, 0},
		{"conflicting anchors", user + call("a") + result("a") + call("b") + result("b") + final, map[string]string{"a": "101", "b": "102"}, 0},
		{"missing result", user + call("a") + final, map[string]string{"a": "101"}, 0},
		{"interrupted by user", user + call("a") + user + final, map[string]string{"a": "101"}, 0},
		{"foreign result", user + call("a") + result("b") + final, map[string]string{"a": "101"}, 0},
		{"partial line", user + call("a") + result("a") + final[:len(final)-1], map[string]string{"a": "101"}, 0},
		{"no native boundary", call("a") + result("a") + final + call("b") + result("b") + final, map[string]string{"a": "101", "b": "102"}, 2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			links := doubaoTranscriptLinks(context.Background(), []byte(tc.raw), tc.turns)
			if len(links) != tc.want {
				t.Fatalf("links=%v", links)
			}
			if tc.name == "two rounds" {
				counts := map[string]int{}
				for _, l := range links {
					if l.Phase == "final" {
						counts[l.Turn]++
					}
				}
				if counts["101"] != 1 || counts["102"] != 1 {
					t.Fatal(counts)
				}
			}
		})
	}
}
