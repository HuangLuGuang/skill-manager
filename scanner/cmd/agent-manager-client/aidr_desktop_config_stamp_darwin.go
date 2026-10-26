package main

import (
	"os"
	"syscall"
)

func desktopConfigChangeTime(info os.FileInfo) int64 {
	if stat, ok := info.Sys().(*syscall.Stat_t); ok {
		return stat.Ctimespec.Sec*1e9 + stat.Ctimespec.Nsec
	}
	return 0
}
