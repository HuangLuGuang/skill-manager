package runtimeobservation

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
)

type outputEmitter struct {
	ctx        context.Context
	writer     io.Writer
	file       *os.File
	descriptor uintptr
}

func newEmitter(ctx context.Context, writer io.Writer) (*outputEmitter, error) {
	value := &outputEmitter{ctx: ctx, writer: writer}
	if file, ok := writer.(*os.File); ok {
		descriptor, err := prepareOutputFile(file)
		if err != nil {
			return nil, fmt.Errorf("runtime_observation_output_setup")
		}
		value.file = file
		value.descriptor = descriptor
	}
	return value, nil
}
func (e *outputEmitter) emit(value Output) error {
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if e.file != nil {
		if err := writeOutputFile(e.ctx, e.file, e.descriptor, data); err != nil {
			return fmt.Errorf("%w: %v", ErrOutputFailure, err)
		}
		return nil
	}
	n, err := e.writer.Write(data)
	if err == nil && n != len(data) {
		err = io.ErrShortWrite
	}
	if err != nil {
		return fmt.Errorf("%w: %v", ErrOutputFailure, err)
	}
	return nil
}
