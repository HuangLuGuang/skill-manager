package managedclient

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
)

// Versioned copies keep the running worker and rollback executable outside the
// desktop bundle. Never overwrite an executable that another process is using.
func stageServiceBinary(home, source string) (string, error) {
	digest, err := executableSHA256(source)
	if err != nil {
		return "", err
	}
	name := "agent-manager-client"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	dir := filepath.Join(RuntimeRoot(home), "service", "versions", digest)
	target := filepath.Join(dir, name)
	if existing, err := executableSHA256(target); err == nil && existing == digest {
		return target, nil
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	input, err := os.Open(source)
	if err != nil {
		return "", err
	}
	defer input.Close()
	output, err := os.CreateTemp(dir, ".stage-")
	if err != nil {
		return "", err
	}
	defer os.Remove(output.Name())
	defer output.Close()
	if _, err = io.Copy(output, input); err != nil {
		return "", err
	}
	if err = output.Chmod(0700); err != nil {
		return "", err
	}
	if err = output.Sync(); err != nil {
		return "", err
	}
	if err = output.Close(); err != nil {
		return "", err
	}
	if copied, e := executableSHA256(output.Name()); e != nil || copied != digest {
		return "", fmt.Errorf("client_service_binary_changed")
	}
	if err = os.Rename(output.Name(), target); err != nil {
		return "", err
	}
	return target, nil
}
