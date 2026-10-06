//go:build windows

package agentlog

import "os"

func openLog(path string) (*os.File, error) { return os.Open(path) }
