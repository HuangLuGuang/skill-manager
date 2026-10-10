package agentlog

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strconv"
	"time"
)

func anchor(f *os.File, offset int64) (string, error) {
	n := min(offset, 256)
	data := make([]byte, n)
	if _, err := f.ReadAt(data, offset-n); err != nil {
		return "", err
	}
	return digest(string(data)), nil
}
func addGap(c *Cursor, reason string) {
	for _, r := range c.Gaps {
		if r == reason {
			return
		}
	}
	c.Gaps = append(c.Gaps, reason)
}

// ReadIncremental returns a proposed cursor. The caller must atomically commit
// events and cursor (P1-02); no file, log, platform or running Agent is mutated.
func ReadIncremental(ctx context.Context, s Source, old Cursor, b Budget, since time.Time) (ReadBatch, error) {
	return ReadWithPolicy(ctx, s, old, b, since, nil)
}
func ReadWithPolicy(ctx context.Context, s Source, old Cursor, b Budget, since time.Time, policy *AuditPolicy, observers ...*SkillObserver) (ReadBatch, error) {
	var observer *SkillObserver
	if len(observers) > 0 && observers[0] != nil {
		observer = observers[0]
	} else {
		observer = NewSkillObserver()
	}
	return readWithPolicy(ctx, s, old, b, since, policy, 0, observer)
}

// replayEnd rebuilds context only, up to an existing committed checkpoint.
func readWithPolicy(ctx context.Context, s Source, old Cursor, b Budget, since time.Time, policy *AuditPolicy, replayEnd int64, observer *SkillObserver) (ReadBatch, error) {
	out := ReadBatch{SchemaVersion: SchemaVersion, Source: s, Events: []Event{}, Cursor: old, Coverage: Coverage{Status: "complete", Reasons: []string{}}}
	expected, e := NewSource(s.Agent, s.Root, s.Path)
	if e != nil || expected.ID != s.ID || !b.valid() {
		return out, errors.New("aidr_log_request_invalid")
	}
	if old.SchemaVersion != 0 {
		if e := ValidateCursor(old, s); e != nil {
			return out, e
		}
	}
	if err := checkPath(s.Path); err != nil {
		out.Coverage.mark("unavailable", ioReason(err))
		return out, nil
	}
	f, err := openLog(s.Path)
	if err != nil {
		out.Coverage.mark("unavailable", ioReason(err))
		return out, nil
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return out, err
	}
	if !info.Mode().IsRegular() {
		out.Coverage.mark("unavailable", "aidr_log_not_regular")
		return out, nil
	}
	current, err := os.Lstat(s.Path)
	if err != nil || !os.SameFile(info, current) || checkPath(s.Path) != nil {
		out.Coverage.mark("unavailable", "aidr_log_source_changed")
		return out, nil
	}
	identity, err := fileIdentity(f, info)
	if err != nil {
		return out, err
	}
	c := old
	c.Gaps = append([]string{}, old.Gaps...)
	reset := ""
	if c.SchemaVersion == 0 {
		if since.IsZero() {
			since = time.Now().Add(-24 * time.Hour)
		}
		c = Cursor{ContextRepairVersion: contextRepairVersion, ProjectionVersion: 2, SchemaVersion: SchemaVersion, ParserVersion: ParserVersion, SourceID: s.ID, FileIdentity: identity, Generation: 1, Since: since, Gaps: []string{}}
	} else if c.FileIdentity != identity {
		reset = "aidr_log_rotated"
	} else if info.Size() < c.Offset {
		reset = "aidr_log_truncated"
	} else {
		a, err := sourceAnchor(s, f, c.Offset)
		if err != nil {
			return out, err
		}
		if a != c.Anchor {
			reset = "aidr_log_rewritten"
		}
	}
	if reset != "" {
		if c.Generation == ^uint64(0) {
			return out, errors.New("aidr_log_generation_exhausted")
		}
		c.FileIdentity = identity
		c.Generation++
		c.Offset = 0
		c.Discarding = false
		c.DiscardStart = 0
		c.ModelContext, c.ModelProvider, c.ModelTurn = nil, "", ""
		c.ModelHeaderRead = false
		c.Session = ""
		c.Turn = ""
		c.CallTurns = nil
		c.QoderLinks = nil
		c.AgentVersion = ""
		c.RecoveryGaps = nil
		c.RecoveryDetailsTruncated = false
		c.ContextRepair = nil
		c.ContextRepairVersion = contextRepairVersion
		if s.Agent != "opencode" {
			addGap(&c, reset)
		}
	}
	if replayEnd == 0 && needsContextRepair(s, c) {
		var checkpoint Cursor
		if c.ContextRepair != nil {
			checkpoint = *c.ContextRepair
		}
		replay, err := readWithPolicy(ctx, s, checkpoint, b, c.Since, nil, c.Offset, observer)
		if err != nil {
			return out, err
		}
		if replay.Cursor.FileIdentity != c.FileIdentity {
			out.Coverage.mark("unavailable", "aidr_log_source_changed")
			return out, nil
		}
		if replay.Cursor.Offset == c.Offset {
			c.Session, c.Turn, c.AgentVersion = replay.Cursor.Session, replay.Cursor.Turn, replay.Cursor.AgentVersion
			c.CallTurns = replay.Cursor.CallTurns
			c.QoderLinks = replay.Cursor.QoderLinks
			c.ModelContext, c.ModelProvider, c.ModelTurn = replay.Cursor.ModelContext, replay.Cursor.ModelProvider, replay.Cursor.ModelTurn
			c.ContextRepair, c.ContextRepairVersion = nil, contextRepairVersion
		} else {
			c.ContextRepair = &replay.Cursor
		}
		out.Cursor, out.Coverage = c, replay.Coverage
		out.Coverage.mark("partial", "aidr_log_read_budget")
		return out, nil
	}
	c.ContextRepairVersion = contextRepairVersion
	if s.Agent == "codex" {
		restoreModelProvider(f, &c)
	}
	// Read a bounded snapshot of the file; appends are handled on the next call.
	end := info.Size()
	if replayEnd > 0 {
		end = min(end, replayEnd)
	}
	remaining := min(end-c.Offset, b.Bytes)
	if _, err = f.Seek(c.Offset, io.SeekStart); err != nil {
		return out, err
	}
	reader := bufio.NewReaderSize(io.LimitReader(f, remaining), min(b.LineBytes+1, 64<<10))
	deadline := time.Now().Add(b.Duration)
	for out.Coverage.Bytes < remaining {
		if ctx.Err() != nil {
			out.Coverage.mark("partial", "aidr_log_canceled")
			break
		}
		if time.Now().After(deadline) || len(out.Events) >= b.Events {
			out.Coverage.mark("partial", "aidr_log_read_budget")
			break
		}
		if c.Discarding {
			part, err := reader.ReadSlice('\n')
			c.Offset += int64(len(part))
			out.Coverage.Bytes += int64(len(part))
			out.Coverage.SkippedBytes += int64(len(part))
			out.Coverage.gap(c.DiscardStart, c.Offset, "aidr_log_record_too_large")
			if err == nil {
				c.Discarding = false
				out.Coverage.Records++
				continue
			}
			if err == bufio.ErrBufferFull {
				continue
			}
			if err == io.EOF {
				out.Coverage.mark("partial", "aidr_log_partial_line")
			} else {
				out.Coverage.mark("unavailable", "aidr_log_io_error")
			}
			break
		}
		var line []byte
		var readErr error
		if s.Agent == "opencode" {
			line, readErr = io.ReadAll(io.LimitReader(reader, int64(b.LineBytes)+1))
			if len(line) > b.LineBytes || int64(len(line)) != info.Size() {
				out.Coverage.mark("partial", "aidr_log_snapshot_incomplete")
				break
			}
		} else {
			line, readErr = readLine(reader, b.LineBytes)
		}
		out.Coverage.Bytes += int64(len(line))
		if readErr != nil {
			switch {
			case errors.Is(readErr, bufio.ErrBufferFull):
				addGap(&c, "aidr_log_record_too_large")
				if !oversizedPreservesContext(s.Agent, line) {
					invalidateContext(&c)
				}
				c.DiscardStart = c.Offset
				c.Offset += int64(len(line))
				out.Coverage.SkippedBytes += int64(len(line))
				out.Coverage.gap(c.DiscardStart, c.Offset, "aidr_log_record_too_large")
				c.Discarding = len(line) == 0 || line[len(line)-1] != '\n'
				if !c.Discarding {
					out.Coverage.Records++
				}
				continue
			case readErr == io.EOF:
				if c.Offset+int64(len(line)) < info.Size() {
					out.Coverage.mark("partial", "aidr_log_read_budget")
				} else {
					out.Coverage.mark("partial", "aidr_log_partial_line")
				}
			default:
				out.Coverage.mark("unavailable", "aidr_log_io_error")
			}
			break
		}
		candidate := c
		candidate.Gaps = append([]string{}, c.Gaps...)
		drafts, parseErr := normalize(s.Agent, line, &candidate)
		if s.Agent == "opencode" {
			drafts, parseErr = normalizeOpenCode(s, line, &candidate)
		}
		if parseErr != nil {
			if s.Agent == "opencode" {
				out.Coverage.mark("partial", parseErr.Error())
				break
			}
			if skip, invalidate := quarantineUnknown(s.Agent, line); skip {
				reason := "aidr_log_optional_record_skipped"
				if invalidate {
					invalidateContext(&c)
					reason = "aidr_log_context_invalidated"
				}
				rememberRecovery(&c, c.Offset, c.Offset+int64(len(line)), reason, line)
				c.Offset += int64(len(line))
				out.Coverage.SkippedBytes += int64(len(line))
				out.Coverage.Records++
				continue
			}
			addGap(&c, parseErr.Error())
			out.Coverage.gap(c.Offset, c.Offset+int64(len(line)), parseErr.Error())
			break
		}
		if len(drafts) > b.Events-len(out.Events) {
			out.Coverage.mark("partial", "aidr_log_event_budget")
			break
		}
		for _, d := range drafts {
			if replayEnd > 0 {
				continue
			}
			if (policy != nil && !policy.CollectionEnabled()) || (!b.CollectionResumeAt.IsZero() && !d.Time.After(b.CollectionResumeAt)) {
				addGap(&candidate, "aidr_audit_collection_disabled")
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
				addGap(&candidate, "aidr_log_session_unknown")
			}
			turn := candidate.Turn
			if s.Agent == "codex" || s.Agent == "qoder-cli" || s.Agent == "workbuddy" {
				turn = d.Turn
			}
			scope := s.ID + ":" + candidate.Session
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
		if len(drafts) == 0 {
			out.Coverage.Ignored++
		}
		candidate.Offset += int64(len(line))
		c = candidate
		out.Coverage.Records++
	}
	c.Anchor, err = sourceAnchor(s, f, c.Offset)
	if err != nil {
		return out, fmt.Errorf("aidr_log_checkpoint_changed")
	}
	for _, gap := range c.RecoveryGaps {
		out.Coverage.gap(gap.Start, gap.End, gap.Reason)
		if len(out.Coverage.Gaps) > 0 && out.Coverage.Gaps[len(out.Coverage.Gaps)-1].Start == gap.Start {
			out.Coverage.Gaps[len(out.Coverage.Gaps)-1].EvidenceDigest = gap.EvidenceDigest
		}
	}
	out.Coverage.GapDetailsTruncated = out.Coverage.GapDetailsTruncated || c.RecoveryDetailsTruncated
	for _, r := range c.Gaps {
		// Older cursors retained a version label as a gap despite parsed records.
		// Keep the cursor history, but determine coverage from actual read failures.
		if r != "aidr_log_version_unverified" {
			out.Coverage.mark("partial", r)
		}
	}
	if c.Offset < info.Size() && out.Coverage.Status == "complete" {
		out.Coverage.mark("partial", "aidr_log_read_budget")
	}
	out.Cursor = c
	return out, nil
}
func readLine(r *bufio.Reader, limit int) ([]byte, error) {
	var result []byte
	for {
		part, err := r.ReadSlice('\n')
		if len(result)+len(part) > limit {
			return append(result, part...), bufio.ErrBufferFull
		}
		result = append(result, part...)
		if err == bufio.ErrBufferFull {
			continue
		}
		return result, err
	}
}
