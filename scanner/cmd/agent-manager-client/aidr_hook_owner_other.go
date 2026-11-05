//go:build !darwin && !linux && !windows

package main

import "errors"

func acquireHookSupervisor(string) (func(), error) {
	return nil, errors.New("aidr_desktop_platform_unsupported")
}
func recoverManagedHookSocket(string) error { return errors.New("aidr_desktop_platform_unsupported") }
