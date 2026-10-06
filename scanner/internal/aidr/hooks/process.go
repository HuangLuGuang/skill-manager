package hooks

// BridgeProcess is receiver-observed provenance, not a tool-to-process link.
// Missing values are represented by an absent record, never by a PID-only guess.
type BridgeProcess struct {
	BootID     string `json:"boot_id"`
	PID        string `json:"pid"`
	PIDVersion string `json:"pidversion"`
	StartUS    string `json:"start_us"`
	Method     string `json:"method"`
	Role       string `json:"role"`
}
