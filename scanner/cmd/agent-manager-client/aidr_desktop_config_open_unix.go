//go:build !windows

package main

import "os"

func openDesktopConfig(path string) (*os.File, error) { return os.Open(path) }

func replaceDesktopConfig(from, to string) error { return os.Rename(from, to) }
