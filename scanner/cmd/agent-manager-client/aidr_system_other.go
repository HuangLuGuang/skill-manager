//go:build !darwin

package main

import (
	"errors"
	"io"
)

func aidrSystem(args []string, out io.Writer) error          { return errors.New("aidr_system_unsupported") }
func systemRuntimeChannel(paths desktopPaths) map[string]any { return nil }
