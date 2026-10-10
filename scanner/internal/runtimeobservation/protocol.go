package runtimeobservation

import (
	"encoding/json"
	"errors"
	"fmt"
)

const ProtocolVersion = 1
const MaxFrameBytes = 64 * 1024

var ErrUnsupported = errors.New("runtime_observation_unsupported_platform")
var ErrOutputFailure = errors.New("runtime_observation_output_failure")

type Frame struct {
	Protocol            int             `json:"protocol"`
	Type                string          `json:"type"`
	MonitorSession      string          `json:"monitor_session,omitempty"`
	StreamStart         string          `json:"stream_start,omitempty"`
	AttributionBaseline string          `json:"attribution_baseline,omitempty"`
	Transport           string          `json:"transport,omitempty"`
	ObserverHealth      string          `json:"observer_health,omitempty"`
	Coverage            string          `json:"coverage,omitempty"`
	Reason              string          `json:"reason,omitempty"`
	Sequence            uint64          `json:"sequence,omitempty"`
	Payload             json.RawMessage `json:"payload,omitempty"`
}

func DecodeFrame(line []byte) (Frame, error) {
	if len(line) == 0 || len(line) > MaxFrameBytes {
		return Frame{}, fmt.Errorf("runtime_observation_frame_size")
	}
	var frame Frame
	if err := json.Unmarshal(line, &frame); err != nil {
		return Frame{}, fmt.Errorf("runtime_observation_invalid_json: %w", err)
	}
	if frame.Protocol != ProtocolVersion {
		return Frame{}, fmt.Errorf("runtime_observation_protocol_version")
	}
	switch frame.Type {
	case "hello", "status", "event":
	default:
		return Frame{}, fmt.Errorf("runtime_observation_frame_type")
	}
	return frame, nil
}
