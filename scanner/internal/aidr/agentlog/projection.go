package agentlog

import (
	"context"
	"encoding/json"
	"strconv"
	"time"
)

func projectDrafts(ctx context.Context, s Source, drafts []draft, candidate *Cursor, c Cursor, identity string, line []byte, policy *AuditPolicy, b Budget, observer *SkillObserver, deadline time.Time, replayEnd int64, out *ReadBatch) {
	for _, d := range drafts {
		if replayEnd > 0 {
			continue
		}
		if (policy != nil && !policy.CollectionEnabled()) || (!b.CollectionResumeAt.IsZero() && !d.Time.After(b.CollectionResumeAt)) {
			addGap(candidate, "aidr_audit_collection_disabled")
			out.Coverage.gap(c.Offset, c.Offset+int64(len(line)), "aidr_audit_collection_disabled")
			out.Coverage.mark("partial", "aidr_audit_collection_disabled")
			out.Coverage.Filtered++
			continue
		}
		if d.Time.Before(c.Since) {
			out.Coverage.Filtered++
			continue
		}
		if d.MessageRole != "" {
			if policy == nil || policy.MessageSchema != 1 || policy.Capture == nil || candidate.Session == "" {
				continue
			}
			message := projectMessage(d, *policy)
			contentHash := digest(canonical(d.Content))
			id := digest("message/1", s.Agent, s.ID, candidate.Session, d.Call, d.MessageRole, d.MessagePhase, contentHash)
			out.Events = append(out.Events, Event{ModelContext: collectedModel(d, policy), SchemaVersion: 3, Message: message, EventID: digest(id, identity, strconv.FormatInt(c.Offset, 10)), LogicalEventID: id, SourceID: s.ID, SourceInstanceID: digest(s.ID, identity, strconv.FormatUint(c.Generation, 10)), SourceSeq: c.Offset + int64(d.Block), RecordOffset: c.Offset, Block: d.Block, Agent: s.Agent, AgentVersion: candidate.AgentVersion, Source: "agent_log", SessionID: candidate.Session, TurnID: d.Turn, CallID: d.Call, LogicalCallID: digest(s.Agent, s.ID, candidate.Session, d.Call), Kind: d.Kind, Outcome: "unknown", ObservedAt: d.Time, ReceivedAt: time.Now().UTC(), ContentDigest: contentHash, ContentBytes: len(d.Content), EvidenceDigest: digest(string(line)), ProcessRelation: "unknown"})
			continue
		}
		if candidate.Session == "" {
			addGap(candidate, "aidr_log_session_unknown")
		}
		turn := candidate.Turn
		if logAdapters[s.Agent].DraftTurn {
			turn = d.Turn
		}
		scope := s.ID + ":" + candidate.Session
		if candidate.Session == "" {
			scope += ":" + strconv.FormatUint(c.Generation, 10)
		}
		content := canonical(d.Content)
		contentDigest := digest(content)
		version := candidate.ProjectionVersion
		if version == 0 {
			version = 1
		}
		var previousIDs []string
		if policy != nil {
			// Preserve tombstone compatibility across projector upgrades and rotation.
			for _, legacyVersion := range []int{1, 2} {
				legacyJSON, _ := json.Marshal(projectBehaviorVersion(d, legacyVersion))
				previousIDs = append(previousIDs, digest("behavior/"+strconv.Itoa(legacyVersion), s.Agent, scope, turn, d.Call, d.Kind, d.Tool, d.Outcome, contentDigest, string(legacyJSON)))
			}
			version = 3
		}
		behavior := projectBehaviorPolicy(d, version, policy)
		var skillUse *SkillUse
		if d.Kind == "tool_call" {
			skillUse = ProjectSkillUse(s.Agent, d.Tool, d.Cwd, d.Content, policy)
		}
		if d.Kind == "tool_result" && d.Outcome != "error" {
			skillUse = ProjectSkillResult(s.Agent, d.ResultTool, d.Content, d.ResultMeta, policy)
		}
		if skillUse != nil && skillUse.Path != "" {
			observationCtx, cancelObservation := context.WithDeadline(ctx, deadline)
			observer.Observe(observationCtx, skillUse, policy)
			cancelObservation()
		}
		namespace := "behavior/" + strconv.Itoa(version)
		behaviorJSON, _ := json.Marshal(behavior)
		id := digest(namespace, s.Agent, scope, turn, d.Call, d.Kind, d.Tool, d.Outcome, contentDigest, string(behaviorJSON))
		if policy != nil {
			id = digest(namespace, s.Agent, scope, turn, d.Call, d.Kind, d.Tool, d.Outcome, contentDigest)
		}
		out.Events = append(out.Events, Event{ModelContext: collectedModel(d, policy), UserScope: sourceUserScope(), SkillUse: skillUse, PreviousLogicalIDs: previousIDs, SchemaVersion: 2, Behavior: behavior, EventID: digest(namespace, s.ID, identity, strconv.FormatUint(c.Generation, 10), strconv.FormatInt(c.Offset, 10), strconv.Itoa(d.Block), string(line)), LogicalEventID: id, SourceID: s.ID, SourceInstanceID: digest(s.ID, identity, strconv.FormatUint(c.Generation, 10)), SourceSeq: c.Offset + int64(d.Block), RecordOffset: c.Offset, Block: d.Block, Agent: s.Agent, AgentVersion: candidate.AgentVersion, Source: "agent_log", SessionID: candidate.Session, TurnID: turn, CallID: d.Call, LogicalCallID: digest(s.Agent, scope, turn, d.Call), Kind: d.Kind, Tool: d.Tool, Outcome: d.Outcome, ObservedAt: d.Time, ReceivedAt: time.Now().UTC(), ContentDigest: contentDigest, ContentBytes: len(d.Content), EvidenceDigest: digest(string(line)), ProcessRelation: "unknown"})
	}
}
