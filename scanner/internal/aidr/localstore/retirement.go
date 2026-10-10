package localstore

import (
	"database/sql"
	"errors"
	"skill-manager/scanner/internal/aidr/agentlog"
	"time"
)

const retirementReason = "aidr_audit_history_retention"
const futureReason = "aidr_log_timestamp_future"
const futureTolerance = 5 * time.Minute

func retiredThrough(tx *sql.Tx) (time.Time, error) {
	var raw string
	err := tx.QueryRow(`SELECT value FROM metadata WHERE key='retired_through'`).Scan(&raw)
	if errors.Is(err, sql.ErrNoRows) {
		return time.Time{}, nil
	}
	if err != nil {
		return time.Time{}, err
	}
	at, err := time.Parse(time.RFC3339Nano, raw)
	if err != nil {
		return time.Time{}, ErrInvalid
	}
	return at, nil
}

// Retained identities are checked normally, including pending older events.
// Unknown identities outside the admission window are coverage gaps, not uploads.
func retireFilter(tx *sql.Tx, events []agentlog.Event, coverage agentlog.Coverage) ([]agentlog.Event, agentlog.Coverage, error) {
	boundary, err := retiredThrough(tx)
	if err != nil {
		return nil, coverage, err
	}
	latest := time.Now().Add(futureTolerance)
	out := make([]agentlog.Event, 0, len(events))
	for _, e := range events {
		var exists int
		if err = tx.QueryRow(`SELECT (SELECT count(*) FROM logical_events WHERE id=?)+(SELECT count(*) FROM evidence WHERE id=?)`, e.LogicalEventID, e.EventID).Scan(&exists); err != nil {
			return nil, coverage, err
		}
		reason := retirementReason
		if e.ObservedAt.After(latest) {
			reason = futureReason
		}
		if exists != 0 || (reason != futureReason && (boundary.IsZero() || e.ObservedAt.After(boundary))) {
			out = append(out, e)
			continue
		}
		coverage.Filtered++
		if coverage.Status == "complete" {
			coverage.Status = "partial"
		}
		found := false
		for _, existing := range coverage.Reasons {
			if existing == reason {
				found = true
				break
			}
		}
		if !found {
			coverage.Reasons = append(coverage.Reasons, reason)
		}
		if len(coverage.Gaps) < 32 {
			coverage.Gaps = append(coverage.Gaps, agentlog.Gap{Start: e.RecordOffset, End: e.RecordOffset + 1, Reason: reason})
		} else {
			coverage.GapDetailsTruncated = true
		}
	}
	return out, coverage, nil
}
