#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import re
import ssl
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import aiohttp


PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
]

FINGERPRINTS = {
    "title_keywords": ["openclaw", "open claw"],
    "body_keywords": ["openclaw", "open-claw", "/api/v1/claw"],
    "api_endpoints": ["/api/version", "/api/health", "/api/v1/status"],
    "header_keywords": ["openclaw", "claw"],
}


def is_private_ip(ip: ipaddress._BaseAddress) -> bool:
    return any(ip in net for net in PRIVATE_NETWORKS)


def validate_and_expand_target(target: str, default_ports: list[int]) -> list[tuple[str, int]]:
    target = target.strip()
    if not target:
        return []

    if target.startswith(("http://", "https://")):
        parsed = urlparse(target)
        if not parsed.hostname:
            raise ValueError(f"Invalid URL target: {target}")
        ip = ipaddress.ip_address(parsed.hostname)
        if not is_private_ip(ip):
            raise ValueError(f"Refusing public target: {target}")
        return [(str(ip), parsed.port or default_ports[0])]

    if "-" in target and "/" not in target:
        start_raw, end_raw = target.split("-", 1)
        start_ip = ipaddress.ip_address(start_raw.strip())
        end_ip = ipaddress.ip_address(end_raw.strip())
        if not (is_private_ip(start_ip) and is_private_ip(end_ip)):
            raise ValueError(f"Refusing public target range: {target}")
        results: list[tuple[str, int]] = []
        current = int(start_ip)
        while current <= int(end_ip):
            for port in default_ports:
                results.append((str(ipaddress.ip_address(current)), port))
            current += 1
        return results

    try:
        network = ipaddress.ip_network(target, strict=False)
        if not is_private_ip(network.network_address):
            raise ValueError(f"Refusing public target network: {target}")
        return [(str(ip), port) for ip in network.hosts() for port in default_ports]
    except ValueError:
        pass

    if ":" in target:
        host_raw, port_raw = target.rsplit(":", 1)
        ip = ipaddress.ip_address(host_raw)
        port = int(port_raw)
        if not is_private_ip(ip):
            raise ValueError(f"Refusing public target: {target}")
        return [(str(ip), port)]

    ip = ipaddress.ip_address(target)
    if not is_private_ip(ip):
        raise ValueError(f"Refusing public target: {target}")
    return [(str(ip), port) for port in default_ports]


async def tcp_probe(ip: str, port: int, timeout: float, semaphore: asyncio.Semaphore) -> tuple[str, int] | None:
    async with semaphore:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return (ip, port)
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return None


async def http_fingerprint(
    ip: str,
    port: int,
    timeout: float,
    semaphore: asyncio.Semaphore,
    session: aiohttp.ClientSession,
) -> dict[str, Any] | None:
    result = {
        "ip": ip,
        "port": port,
        "status": "open_non_http",
        "http_status": None,
        "title": "",
        "server": "",
        "fingerprint": [],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    schemes = ["https", "http"] if port in (443, 8443) else ["http", "https"]

    for scheme in schemes:
        url = f"{scheme}://{ip}:{port}/"
        async with semaphore:
            try:
                ssl_ctx = False if scheme == "http" else ssl.create_default_context()
                if scheme == "https" and isinstance(ssl_ctx, ssl.SSLContext):
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    ssl=ssl_ctx,
                    allow_redirects=True,
                    max_redirects=2,
                ) as response:
                    result["http_status"] = response.status
                    result["server"] = response.headers.get("Server", "")
                    body = await response.text(encoding="utf-8", errors="ignore")
                    body_lower = body[:50000].lower()
                    title_match = re.search(r"<title>(.*?)</title>", body_lower, re.DOTALL)
                    if title_match:
                        result["title"] = title_match.group(1).strip()[:100]
                    for kw in FINGERPRINTS["title_keywords"]:
                        if kw in result["title"].lower():
                            result["fingerprint"].append(f"title:{kw}")
                    for kw in FINGERPRINTS["body_keywords"]:
                        if kw in body_lower:
                            result["fingerprint"].append(f"body:{kw}")
                    for header_name, header_value in response.headers.items():
                        lower_value = header_value.lower()
                        for kw in FINGERPRINTS["header_keywords"]:
                            if kw in lower_value:
                                result["fingerprint"].append(f"header:{header_name}")
                    if result["fingerprint"]:
                        result["status"] = "confirmed"
                        return result
            except (aiohttp.ClientError, asyncio.TimeoutError, ssl.SSLError, OSError, UnicodeDecodeError):
                continue

    for endpoint in FINGERPRINTS["api_endpoints"]:
        url = f"http://{ip}:{port}{endpoint}"
        async with semaphore:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=False) as response:
                    if response.status in (200, 401, 403):
                        body = await response.text(encoding="utf-8", errors="ignore")
                        body_lower = body[:10000].lower()
                        for kw in FINGERPRINTS["body_keywords"] + FINGERPRINTS["title_keywords"]:
                            if kw in body_lower:
                                result["fingerprint"].append(f"api:{endpoint}:{kw}")
                        if result["fingerprint"]:
                            result["status"] = "confirmed"
                            result["http_status"] = response.status
                            return result
                        result["status"] = "suspicious"
                        result["http_status"] = response.status
                        return result
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, UnicodeDecodeError):
                continue

    if result["http_status"] is not None:
        result["status"] = "suspicious"
    return result


async def scan_openclaw(
    targets: list[str],
    ports: list[int],
    timeout: float,
    concurrency: int,
) -> dict[str, Any]:
    expanded: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for target in targets:
        for item in validate_and_expand_target(target, ports):
            if item not in seen:
                seen.add(item)
                expanded.append(item)

    semaphore = asyncio.Semaphore(max(concurrency, 1))
    tcp_results = await asyncio.gather(
        *(tcp_probe(ip, port, timeout, semaphore) for ip, port in expanded)
    )
    open_ports = [result for result in tcp_results if result is not None]

    connector = aiohttp.TCPConnector(limit=max(concurrency, 1), enable_cleanup_closed=True, force_close=True)
    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": "OpenClawDiscoverySkill/1.0"},
    ) as session:
        fingerprint_results = await asyncio.gather(
            *(http_fingerprint(ip, port, timeout + 1, semaphore, session) for ip, port in open_ports)
        )
    findings = [result for result in fingerprint_results if result is not None]
    return {
        "scan_targets": targets,
        "expanded_target_count": len(expanded),
        "open_port_count": len(open_ports),
        "confirmed_count": sum(1 for item in findings if item["status"] == "confirmed"),
        "suspicious_count": sum(1 for item in findings if item["status"] == "suspicious"),
        "results": findings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenClaw private network discovery skill")
    parser.add_argument("--target", action="append", required=True, help="Target IP, CIDR, URL, or range")
    parser.add_argument("--port", default="18789", help="Comma-separated ports")
    parser.add_argument("--timeout", type=float, default=3.0, help="Probe timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=50, help="Max concurrency")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ports = [int(item.strip()) for item in args.port.split(",") if item.strip()]
    result = asyncio.run(
        scan_openclaw(
            targets=args.target,
            ports=ports,
            timeout=args.timeout,
            concurrency=args.concurrency,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
