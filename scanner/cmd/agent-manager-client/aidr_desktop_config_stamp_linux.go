package main

import (
	"os"
	"syscall"
)

func desktopConfigChangeTime(info os.FileInfo) int64 {
	if stat, ok := info.Sys().(*syscall.Stat_t); ok {
		return stat.Ctim.Sec*1e9 + stat.Ctim.Nsec
	}
	return 0
}
