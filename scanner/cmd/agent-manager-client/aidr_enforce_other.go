//go:build !darwin

package main

import (
	"errors"
	"io"
)

func aidrEnforce(_ []string, _ io.Writer) error {
	return errors.New("aidr_enforcement_platform_unsupported")
}
