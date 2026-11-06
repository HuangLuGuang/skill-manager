"""IP literals in command text; no DNS, shell expansion or network requests."""
import ipaddress
import re

from pydantic import Field, model_validator
from .aidr_behavior import Strict


class NetworkCondition(Strict):
    subnets: list[str] = Field(min_length=1, max_length=16)

    @model_validator(mode='after')
    def valid(self):
        for subnet in self.subnets:
            if len(subnet) > 64 or '%' in subnet or not re.fullmatch(r'[0-9A-Fa-f:.]+/(?:0|[1-9][0-9]{0,2})', subnet):
                raise ValueError('hook_command_subnet_invalid')
            ipaddress.ip_network(subnet, strict=False)
        return self


def network_hits(networks, command):
    prefixes = [(value, ipaddress.ip_network(value, strict=False)) for value in networks['subnets']]
    hits, seen = [], set()
    for token in re.findall(r'[A-Za-z0-9_.:%-]+', command):
        if len(token) > 64:
            continue
        # IPv4 host:port is unambiguous; IPv6 ports require brackets.
        if token.count(':') == 1 and '.' in token:
            host, port = token.split(':')
            if 1 <= len(port) <= 5 and port.isascii() and port.isdigit() and 1 <= int(port) <= 65535:
                token = host
        if '%' in token:
            continue
        try:
            address = ipaddress.ip_address(token)
        except ValueError:
            continue
        for subnet, prefix in prefixes:
            key = (str(address), subnet)
            if address in prefix and key not in seen:
                hits.append({'ip': str(address), 'subnet': subnet})
                seen.add(key)
    return hits
