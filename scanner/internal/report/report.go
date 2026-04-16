package report

import (
	"encoding/json"
	"os"
	"time"

	"skill-manager/scanner/internal/client"
	"skill-manager/scanner/internal/manifest"
	"skill-manager/scanner/internal/precheck"
)

type SkillResult struct {
	Path          string              `json:"path"`
	Name          string              `json:"name"`
	Description   string              `json:"description,omitempty"`
	Fingerprint   string              `json:"fingerprint"`
	FileCount     int                 `json:"file_count"`
	TotalBytes    int64               `json:"total_bytes"`
	LocalFindings []precheck.Finding  `json:"local_findings"`
	PackagePath   string              `json:"package_path,omitempty"`
	Submitted     bool                `json:"submitted"`
	SubmitError   string              `json:"submit_error,omitempty"`
	Submission    client.SubmitResult `json:"submission,omitempty"`
	Manifest      manifest.Manifest   `json:"manifest"`
}

type Report struct {
	GeneratedAt time.Time     `json:"generated_at"`
	Root        string        `json:"root"`
	Found       int           `json:"found"`
	Submitted   int           `json:"submitted"`
	Failed      int           `json:"failed"`
	Skills      []SkillResult `json:"skills"`
}

func Write(path string, r Report) error {
	payload, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(payload, '\n'), 0o644)
}
