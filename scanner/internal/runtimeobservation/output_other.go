//go:build !darwin

package runtimeobservation

import (
	"context"
	"os"
)

func prepareOutputFile(file *os.File) (uintptr, error) { return file.Fd(), nil }
func writeOutputFile(_ context.Context, file *os.File, _ uintptr, data []byte) error {
	_, err := file.Write(data)
	return err
}
