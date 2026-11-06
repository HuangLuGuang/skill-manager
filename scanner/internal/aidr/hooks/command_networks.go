package hooks

import (
	"net/netip"
	"regexp"
	"strconv"
	"strings"
)

type NetworkCondition struct {
	Subnets []string `json:"subnets"`
}

var subnetSyntax = regexp.MustCompile(`^[0-9A-Fa-f:.]+/(0|[1-9][0-9]{0,2})$`)
var ipTokens = regexp.MustCompile(`[A-Za-z0-9_.:%-]+`)

func (n *NetworkCondition) valid() bool {
	if len(n.Subnets) == 0 || len(n.Subnets) > 16 {
		return false
	}
	for _, subnet := range n.Subnets {
		if len(subnet) > 64 || !subnetSyntax.MatchString(subnet) {
			return false
		}
		if _, err := netip.ParsePrefix(subnet); err != nil {
			return false
		}
	}
	return true
}

func (n *NetworkCondition) matches(command string) bool {
	prefixes := make([]netip.Prefix, 0, len(n.Subnets))
	for _, subnet := range n.Subnets {
		prefix, err := netip.ParsePrefix(subnet)
		if err != nil {
			return false
		}
		prefixes = append(prefixes, prefix.Masked())
	}
	for _, token := range ipTokens.FindAllString(command, -1) {
		if len(token) > 64 || strings.Contains(token, "%") {
			continue
		}
		// IPv4 host:port is unambiguous; IPv6 ports require brackets.
		if strings.Count(token, ":") == 1 && strings.Contains(token, ".") {
			host, port, _ := strings.Cut(token, ":")
			if len(port) >= 1 && len(port) <= 5 && strings.Trim(port, "0123456789") == "" {
				if value, err := strconv.Atoi(port); err == nil && value >= 1 && value <= 65535 {
					token = host
				}
			}
		}
		address, err := netip.ParseAddr(token)
		if err != nil {
			continue
		}
		for _, prefix := range prefixes {
			if prefix.Contains(address) {
				return true
			}
		}
	}
	return false
}
