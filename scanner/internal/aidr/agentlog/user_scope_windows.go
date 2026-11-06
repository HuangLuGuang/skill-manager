package agentlog

import "skill-manager/scanner/internal/aidr/privatefs"

func sourceUserScope() string {
	sid, err := privatefs.UserSID()
	if err != nil {
		return ""
	}
	return sid
}
