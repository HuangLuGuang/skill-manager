package agentlog

import (
	"os"
	"syscall"
)

func skillChangeTime(info os.FileInfo) int64 {
	if info != nil {
		if st, ok := info.Sys().(*syscall.Stat_t); ok {
			return st.Ctim.Sec*1e9 + st.Ctim.Nsec
		}
	}
	return 0
}
