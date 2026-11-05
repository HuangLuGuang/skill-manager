package localstore

import (
	"net/url"
	"path/filepath"
)

func SQLiteURI(path, query string) string {
	path = filepath.ToSlash(path)
	if len(path) >= 2 && path[1] == ':' {
		path = "/" + path
	}
	return (&url.URL{Scheme: "file", Path: path, RawQuery: query}).String()
}
