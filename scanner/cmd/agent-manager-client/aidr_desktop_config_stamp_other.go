//go:build !darwin && !linux

package main

import "os"

func desktopConfigChangeTime(os.FileInfo) int64 { return 0 }
