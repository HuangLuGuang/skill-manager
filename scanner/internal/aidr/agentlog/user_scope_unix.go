//go:build !windows

package agentlog

import (
	"os"
	"strconv"
)

func sourceUserScope() string {
	if uid := os.Getuid(); uid >= 0 {
		return strconv.Itoa(uid)
	}
	return ""
}
