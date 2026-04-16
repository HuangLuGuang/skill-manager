package packager

import (
	"archive/zip"
	"io"
	"os"
	"path/filepath"
	"strings"

	"skill-manager/scanner/internal/manifest"
)

func CreateZip(root string, m manifest.Manifest, outputPath string) error {
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil {
		return err
	}
	file, err := os.Create(outputPath)
	if err != nil {
		return err
	}
	defer file.Close()

	zw := zip.NewWriter(file)
	defer zw.Close()

	for _, entry := range m.Files {
		if strings.HasPrefix(entry.Path, "../") || filepath.IsAbs(entry.Path) {
			continue
		}
		sourcePath := filepath.Join(root, filepath.FromSlash(entry.Path))
		info, err := os.Stat(sourcePath)
		if err != nil {
			return err
		}
		header, err := zip.FileInfoHeader(info)
		if err != nil {
			return err
		}
		header.Name = entry.Path
		header.Method = zip.Deflate
		writer, err := zw.CreateHeader(header)
		if err != nil {
			return err
		}
		source, err := os.Open(sourcePath)
		if err != nil {
			return err
		}
		_, copyErr := io.Copy(writer, source)
		closeErr := source.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	return nil
}
