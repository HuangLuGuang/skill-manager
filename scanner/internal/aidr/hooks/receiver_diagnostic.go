package hooks

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net/url"
	"os"
)

type ReceiverIdentity struct {
	PID       int    `json:"pid"`
	StartedAt string `json:"started_at"`
	Server    string `json:"server"`
	Socket    string `json:"socket"`
	Queue     string `json:"queue"`
}

type ReceiverDiagnostic struct {
	Ownership        string            `json:"ownership"`
	Socket           string            `json:"socket"`
	Queue            string            `json:"queue"`
	ExpectedServer   string            `json:"expected_server"`
	Device           string            `json:"device"`
	PID              int               `json:"pid,omitempty"`
	UID              uint32            `json:"uid"`
	ProcessStartedAt string            `json:"process_started_at,omitempty"`
	Executable       string            `json:"executable,omitempty"`
	Receiver         *ReceiverIdentity `json:"receiver,omitempty"`
	State            *StoreStatus      `json:"state,omitempty"`
	Code             string            `json:"code"`
	AuditGap         *BridgeGap        `json:"audit_gap,omitempty"`
	AuditGapCode     string            `json:"audit_gap_code,omitempty"`
}

func diagnosticServer(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || (u.Scheme != "https" && u.Scheme != "http") {
		return ""
	}
	u.User, u.RawQuery, u.Fragment, u.RawFragment = nil, "", "", ""
	return u.String()
}
func executableDigest(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return ""
	}
	return hex.EncodeToString(h.Sum(nil))
}
