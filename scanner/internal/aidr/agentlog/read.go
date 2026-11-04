package agentlog

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"maps"
	"os"
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
	if read := logAdapters[s.Agent].Read; read != nil {
		return read(ctx, s, old, b, since, policy, observer)
	}
	return readWithPolicy(ctx, s, old, b, since, policy, 0, false, observer)
}

// replayEnd bounds repair to the committed checkpoint; replayEvents also restores projections.
func readWithPolicy(ctx context.Context, s Source, old Cursor, b Budget, since time.Time, policy *AuditPolicy, replayEnd int64, replayEvents bool, observer *SkillObserver) (ReadBatch, error) {
	repairVersion := repairVersionFor(s.Agent)
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
		c = Cursor{ContextRepairVersion: repairVersion, ProjectionVersion: 2, SchemaVersion: SchemaVersion, ParserVersion: ParserVersion, SourceID: s.ID, FileIdentity: identity, Generation: 1, Since: since, Gaps: []string{}}
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
		c.TraeHooks, c.TraeInput = nil, ""
		c.QoderLinks = nil
		c.AgentVersion = ""
		c.RecoveryGaps = nil
		c.RecoveryDetailsTruncated = false
		c.ContextRepair = nil
		c.ContextRepairVersion = repairVersion
		if !logAdapters[s.Agent].Snapshot {
			addGap(&c, reset)
		}
	}
	if s.Agent == "codex" && c.Offset == 0 && policy != nil && policy.CompletionSchema > 0 {
		c.CompletionSchema = policy.CompletionSchema
	}
	completionReplay := s.Agent == "codex" && policy != nil && c.CompletionSchema < policy.CompletionSchema
	reproject := replayEnd == 0 && (codexMetadataReplay(f, s, c) || completionReplay)
	if replayEnd == 0 && (reproject || needsContextRepair(s, c)) {
		var checkpoint Cursor
		if c.ContextRepair != nil && (!reproject || c.ContextRepair.ContextRepairVersion == repairVersion) && (!completionReplay || c.ContextRepair.CompletionSchema >= policy.CompletionSchema) {
			checkpoint = *c.ContextRepair
		} else if reproject {
			checkpoint = Cursor{SchemaVersion: SchemaVersion, ParserVersion: ParserVersion,
				SourceID: s.ID, FileIdentity: c.FileIdentity, Generation: c.Generation,
				Anchor: digest(""), Since: c.Since, ProjectionVersion: c.ProjectionVersion,
				ContextRepairVersion: repairVersion}
		}
		var replayPolicy *AuditPolicy
		if reproject {
			replayPolicy = policy
		}
		replay, err := readWithPolicy(ctx, s, checkpoint, b, c.Since, replayPolicy, c.Offset, reproject, observer)
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
			c.ContextRepair, c.ContextRepairVersion = nil, repairVersion
			if completionReplay {
				c.CompletionSchema = policy.CompletionSchema
			}
			if reproject {
				c.Gaps, c.RecoveryGaps = replay.Cursor.Gaps, replay.Cursor.RecoveryGaps
				c.RecoveryDetailsTruncated = replay.Cursor.RecoveryDetailsTruncated
			}
		} else {
			c.ContextRepair = &replay.Cursor
		}
		out.Cursor, out.Coverage = c, replay.Coverage
		out.Events = replay.Events
		out.Coverage.mark("partial", "aidr_log_read_budget")
		return out, nil
	}
	c.ContextRepairVersion = repairVersion
	if restore := logAdapters[s.Agent].Restore; restore != nil {
		restore(f, &c)
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
		if logAdapters[s.Agent].Snapshot {
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
		candidate.TraeHooks = maps.Clone(c.TraeHooks)
		candidate.Gaps = append([]string{}, c.Gaps...)
		drafts, parseErr := normalizeSource(s, line, &candidate)
		if parseErr != nil {
			if logAdapters[s.Agent].Snapshot {
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
		projectionEnd := replayEnd
		if replayEvents {
			projectionEnd = 0
		}
		firstEvent := len(out.Events)
		projectDrafts(ctx, s, drafts, &candidate, c, identity, line, policy, b, observer, deadline, projectionEnd, &out)
		if replayEvents {
			for i := firstEvent; i < len(out.Events); i++ {
				// Preserve the old immutable evidence with its original missing identity.
				out.Events[i].EventID = digest("context-repair/4", out.Events[i].EventID, out.Events[i].LogicalEventID)
			}
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
