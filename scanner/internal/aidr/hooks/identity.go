package hooks

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"time"
)

// IDs carry bridge creation time, not an asserted host event time. New intake
// expires after 24 hours, allowing acknowledged receipts to be pruned safely
// after 48 hours without re-projecting a historical retry under a new policy.
func NewEventID() (string, error) {
	var b [16]byte
	binary.BigEndian.PutUint64(b[:8], uint64(time.Now().UnixMilli()))
	if _, err := rand.Read(b[8:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}

func freshEventID(id string, now time.Time) bool {
	b, err := hex.DecodeString(id)
	if err != nil || len(b) != 16 {
		return false
	}
	n := binary.BigEndian.Uint64(b[:8])
	return n >= uint64(now.Add(-24*time.Hour).UnixMilli()) && n <= uint64(now.Add(2*time.Minute).UnixMilli())
}
