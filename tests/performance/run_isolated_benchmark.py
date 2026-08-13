#!/usr/bin/env python3
"""Run bounded concurrency benchmarks against the isolated Docker stack."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import os
import platform
import statistics
import time
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx


LEVELS = [1, 2, 5, 10, 20, 40]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


async def measure(
    label: str,
    concurrency: int,
    requests: int,
    operation: Callable[[int], Awaitable[httpx.Response]],
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: dict[str, int] = {}

    async def one(index: int) -> None:
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await operation(index)
                status = str(response.status_code)
            except Exception as exc:  # benchmark records failures instead of aborting the run
                status = f"error:{type(exc).__name__}"
            latencies.append((time.perf_counter() - started) * 1000)
            statuses[status] = statuses.get(status, 0) + 1

    started = time.perf_counter()
    await asyncio.gather(*(one(index) for index in range(requests)))
    elapsed = time.perf_counter() - started
    successes = statuses.get("200", 0) + statuses.get("202", 0)
    result = {
        "case": label,
        "concurrency": concurrency,
        "requests": requests,
        "successes": successes,
        "errors": requests - successes,
        "status_counts": statuses,
        "elapsed_s": round(elapsed, 3),
        "throughput_rps": round(successes / elapsed, 2) if elapsed else 0.0,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 2),
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
            "max": round(max(latencies), 2),
        },
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def skill_zip(name: str, *, executable: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: Isolated scan benchmark\n---\n\n# {name}\n",
        )
        if executable:
            archive.writestr("main.py", "print('benchmark sandbox probe')\n")
    return buffer.getvalue()


async def wait_for_skill(client: httpx.AsyncClient, auth: dict[str, str], skill_id: str) -> dict:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = await client.get(f"/api/v1/skills/{skill_id}", headers=auth)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "PENDING":
            return payload
        await asyncio.sleep(0.1)
    raise TimeoutError(f"skill {skill_id} did not finish")


async def scan_case(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    label: str,
    count: int,
    params: dict[str, str],
    *,
    executable: bool = False,
) -> dict[str, Any]:
    accepted_ms: list[float] = []
    total_ms: list[float] = []
    scan_ms: list[float] = []
    analyzer_ms: dict[str, list[float]] = {}

    async def submit(index: int) -> None:
        name = f"bench-{label}-{int(time.time() * 1000)}-{index}"
        started = time.perf_counter()
        response = await client.post(
            "/api/v1/skills/submit-zip",
            headers=auth,
            params={"origin": "internal", **params},
            files={"file": (f"{name}.zip", skill_zip(name, executable=executable), "application/zip")},
        )
        accepted_ms.append((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        payload = response.json()
        skill_id = payload.get("version_id") or payload.get("skill_id")
        finished = await wait_for_skill(client, auth, skill_id)
        total_ms.append((time.perf_counter() - started) * 1000)
        vetting = finished.get("vetting") or {}
        scan_ms.append(float(vetting.get("scan_duration_seconds") or 0) * 1000)
        timings = ((vetting.get("scan_report") or {}).get("analyzer_timings") or {})
        for analyzer, value in timings.items():
            duration = value.get("duration_ms") if isinstance(value, dict) else value
            if isinstance(duration, (int, float)):
                analyzer_ms.setdefault(analyzer, []).append(float(duration))

    started = time.perf_counter()
    await asyncio.gather(*(submit(index) for index in range(count)))
    elapsed = time.perf_counter() - started
    return {
        "case": label,
        "parallel_submissions": count,
        "elapsed_s": round(elapsed, 3),
        "completed_per_minute": round(count / elapsed * 60, 2),
        "acceptance_latency_ms": {
            "p50": round(percentile(accepted_ms, 0.50), 2),
            "p95": round(percentile(accepted_ms, 0.95), 2),
        },
        "end_to_end_latency_ms": {
            "p50": round(percentile(total_ms, 0.50), 2),
            "p95": round(percentile(total_ms, 0.95), 2),
        },
        "reported_scan_ms": {
            "p50": round(percentile(scan_ms, 0.50), 2),
            "p95": round(percentile(scan_ms, 0.95), 2),
        },
        "analyzer_ms_mean": {key: round(statistics.fmean(values), 2) for key, values in analyzer_ms.items()},
    }


async def main(args: argparse.Namespace) -> None:
    if os.environ.get("BENCHMARK_ISOLATED") != "YES":
        raise SystemExit("refusing to run load tests without BENCHMARK_ISOLATED=YES")
    credentials = json.loads(Path(args.credentials).read_text(encoding="utf-8"))
    backend = args.backend.rstrip("/")
    mock = args.mock.rstrip("/")
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=100)
    timeout = httpx.Timeout(30.0, connect=10.0)
    sections = {item.strip() for item in args.sections.split(",") if item.strip()}
    results: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runner": {"python": platform.python_version(), "platform": platform.platform()},
        "method": {
            "concurrency_levels": LEVELS,
            "gateway_requests_per_level": args.requests,
            "mock_upstream_delay_ms": args.upstream_delay_ms,
            "sections": sorted(sections),
        },
        "model_gateway": [],
        "model_upstream_direct": [],
        "mcp_initialize": [],
        "mcp_tools_list": [],
        "mcp_tool_call": [],
        "runtime_signature_verification": [],
        "skill_detection": [],
    }
    output_path = Path(args.output)

    def checkpoint() -> None:
        output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    checkpoint()
    async with httpx.AsyncClient(base_url=backend, timeout=timeout, limits=limits) as client:
        model_headers = {"Authorization": f"Bearer {credentials['model_token']}"}
        mcp_headers = {"Authorization": f"Bearer {credentials['mcp_token']}"}
        runtime_headers = {"Authorization": f"Bearer {credentials['runtime_token']}"}
        runtime_skill = credentials["runtime_skill"]

        if "model" in sections:
            async with httpx.AsyncClient(base_url=mock, timeout=timeout, limits=limits) as direct:
                for concurrency in LEVELS:
                    requests = max(args.requests, concurrency * 2)
                    results["model_upstream_direct"].append(
                        await measure(
                            "mock-openai-direct",
                            concurrency,
                            requests,
                            lambda index: direct.post(
                                "/v1/chat/completions",
                                json={"model": "bench-model", "messages": [{"role": "user", "content": f"ping-{index}"}]},
                            ),
                        )
                    )
                    checkpoint()
                    results["model_gateway"].append(
                        await measure(
                            "model-gateway",
                            concurrency,
                            requests,
                            lambda index: client.post(
                                "/v1/chat/completions",
                                headers=model_headers,
                                json={
                                    "model": "bench-model",
                                    "messages": [{"role": "user", "content": f"ping-{index}"}],
                                    "metadata": {"bypass_pii_check": "true", "conversation_id": f"bench-{concurrency}-{index}"},
                                },
                            ),
                        )
                    )
                    checkpoint()

        for concurrency in LEVELS if sections.intersection({"mcp", "runtime"}) else []:
            requests = max(args.requests, concurrency * 2)
            if "mcp" in sections:
                results["mcp_initialize"].append(
                    await measure(
                        "mcp-initialize",
                        concurrency,
                        requests,
                        lambda index: client.post(
                            "/mcp/benchmark",
                            headers=mcp_headers,
                            json={"jsonrpc": "2.0", "id": index, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                        ),
                    )
                )
                checkpoint()
                results["mcp_tools_list"].append(
                    await measure(
                        "mcp-tools-list",
                        concurrency,
                        requests,
                        lambda index: client.post(
                            "/mcp/benchmark",
                            headers=mcp_headers,
                            json={"jsonrpc": "2.0", "id": index, "method": "tools/list", "params": {}},
                        ),
                    )
                )
                checkpoint()
                results["mcp_tool_call"].append(
                    await measure(
                        "mcp-tool-call",
                        concurrency,
                        requests,
                        lambda index: client.post(
                            "/mcp/benchmark",
                            headers=mcp_headers,
                            json={
                                "jsonrpc": "2.0",
                                "id": index,
                                "method": "tools/call",
                                "params": {"name": "bench__echo", "arguments": {"text": f"ping-{index}"}},
                            },
                        ),
                    )
                )
                checkpoint()
            if "runtime" in sections:
                results["runtime_signature_verification"].append(
                    await measure(
                        "runtime-signature-verification",
                        concurrency,
                        requests,
                        lambda _index: client.post(
                            "/api/v1/access/runtime/verify-skill-signature",
                            headers=runtime_headers,
                            json={
                                "skill_id": runtime_skill["skill_id"],
                                "skill_name": runtime_skill["skill_name"],
                                "local_signature": runtime_skill["local_signature"],
                                "agent_id": credentials["agent_id"],
                            },
                        ),
                    )
                )
                checkpoint()

        if "scan" in sections:
            admin_token = os.environ["BENCH_ADMIN_JWT"]
            admin_headers = {"Authorization": f"Bearer {admin_token}"}
            for label, count, params, executable in [
                ("rules-single-warm", 1, {}, False),
                ("rules-parallel-4", 4, {}, False),
                ("deep-single", 1, {"use_skillspector": "true"}, False),
                ("deep-parallel-4", 4, {"use_skillspector": "true"}, False),
                ("sandbox-single", 1, {"use_sandbox": "true"}, True),
            ]:
                results["skill_detection"].append(
                    await scan_case(client, admin_headers, label, count, params, executable=executable)
                )
                checkpoint()

    results["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    checkpoint()
    print(json.dumps({"output": args.output, "finished": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="http://backend:8000")
    parser.add_argument("--mock", default="http://mock:19090")
    parser.add_argument("--credentials", default="/bench/credentials.json")
    parser.add_argument("--output", default="/bench/results.json")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--upstream-delay-ms", type=int, default=50)
    parser.add_argument("--sections", default="model,mcp,runtime,scan")
    asyncio.run(main(parser.parse_args()))
