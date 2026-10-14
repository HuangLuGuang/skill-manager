package agentlog

import (
	"bytes"
	"encoding/json"
	"regexp"
	"time"
)

var tokenPattern = regexp.MustCompile(`^[A-Za-z0-9_.:/@+-]{1,256}$`)

func token(s string) string {
	if tokenPattern.MatchString(s) {
		return s
	}
	return ""
}
func canonical(raw json.RawMessage) string {
	var value any
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if d.Decode(&value) != nil {
		return string(raw)
	}
	b, _ := json.Marshal(value)
	return string(b)
}

type draft struct {
	ModelContext              *ModelContext
	MessageRole, MessagePhase string
	HookResult                bool
	ResultProjection          func(*Behavior, string, json.RawMessage)
	ResultTool                string
	Turn                      string
	Cwd                       string
	ResultMeta                json.RawMessage
	Call, Kind, Tool, Outcome string
	Content                   json.RawMessage
	Time                      time.Time
	Block                     int
}

func normalize(agent string, raw []byte, c *Cursor) ([]draft, error) {
	return normalizeSource(Source{Agent: agent}, raw, c)
}

// Pending calls survive read budgets and persisted cursors. Completed entries are
// a bounded replay/conflict cache; capacity never evicts an unfinished call.
const maxToolBindings = 512
const completedToolBindings = 64

func rememberTool(c *Cursor, call, turn, tool string, content json.RawMessage) {
	c.CallTurns = append([]CallTurn(nil), c.CallTurns...)
	signature := digest(canonical(content))
	for i := range c.CallTurns {
		binding := &c.CallTurns[i]
		if binding.Call == call {
			if binding.Turn != turn || (binding.Tool != "" && binding.Tool != tool) || (binding.ContentDigest != "" && binding.ContentDigest != signature) {
				binding.Ambiguous = true
				addGap(c, "aidr_log_call_conflict")
			}
			if !binding.Ambiguous {
				binding.Tool = tool
				binding.ContentDigest = signature
			}
			return
		}
	}
	pruneCompletedTools(c, completedToolBindings)
	if len(c.CallTurns) >= maxToolBindings {
		pruneCompletedTools(c, 0)
	}
	if len(c.CallTurns) >= maxToolBindings {
		addGap(c, "aidr_log_call_capacity")
		return
	}
	c.CallTurns = append(c.CallTurns, CallTurn{Call: call, Turn: turn, Tool: tool, ContentDigest: signature})
}

func pruneCompletedTools(c *Cursor, keep int) {
	completed := 0
	for _, binding := range c.CallTurns {
		if binding.Completed {
			completed++
		}
	}
	retained := make([]CallTurn, 0, len(c.CallTurns))
	for _, binding := range c.CallTurns {
		if binding.Completed && completed > keep {
			completed--
			continue
		}
		retained = append(retained, binding)
	}
	c.CallTurns = retained
}

func completeTool(c *Cursor, call, turn string) (string, string) {
	c.CallTurns = append([]CallTurn(nil), c.CallTurns...)
	for i := range c.CallTurns {
		binding := &c.CallTurns[i]
		if binding.Call != call {
			continue
		}
		if binding.Ambiguous || (turn != "" && turn != binding.Turn) {
			addGap(c, "aidr_log_call_conflict")
			return turn, ""
		}
		binding.Completed = true
		resolvedTurn, tool := binding.Turn, binding.Tool
		pruneCompletedTools(c, completedToolBindings)
		return resolvedTurn, tool
	}
	addGap(c, "aidr_log_call_unresolved")
	return turn, ""
}

func boundTool(c *Cursor, call string) string {
	for _, binding := range c.CallTurns {
		if binding.Call == call && !binding.Ambiguous {
			return binding.Tool
		}
	}
	return ""
}
