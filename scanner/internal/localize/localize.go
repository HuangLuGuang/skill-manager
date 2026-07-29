package localize

import (
	"os"
	"strings"
)

func Locale() string {
	value := strings.ToLower(strings.TrimSpace(os.Getenv("AGENT_MANAGER_SCANNER_LANG")))
	if value == "" {
		value = strings.ToLower(strings.TrimSpace(os.Getenv("LANG")))
	}
	if strings.HasPrefix(value, "en") {
		return "en-US"
	}
	return "zh-CN"
}

func Text(zh, en string) string {
	if Locale() == "en-US" {
		return en
	}
	return zh
}
