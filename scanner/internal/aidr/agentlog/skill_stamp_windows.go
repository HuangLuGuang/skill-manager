package agentlog

import "os"

func skillChangeTime(info os.FileInfo) int64 {
	// Windows FileInfo exposes identity and last-write time, checked separately.
	return 0
}
