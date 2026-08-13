#!/usr/bin/env python3
"""Measure registry query latency after loading synthetic Skill families."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    index = min(len(values) - 1, int(round((len(values) - 1) * p)))
    return values[index]


def main(args: argparse.Namespace) -> None:
    if os.environ.get("BENCHMARK_ISOLATED") != "YES":
        raise SystemExit("refusing to insert synthetic Skills without BENCHMARK_ISOLATED=YES")
    db_path = Path(args.database)
    connection = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    existing = connection.execute("SELECT count(*) FROM skill_families WHERE name LIKE 'capacity-bench-%'").fetchone()[0]
    if existing < args.count:
        family_rows = []
        skill_rows = []
        for index in range(existing, args.count):
            family_id = f"cap-{index:08d}"
            skill_id = f"capv-{index:08d}"
            name = f"capacity-bench-{index:08d}"
            payload = json.dumps(
                {
                    "skill_id": skill_id,
                    "family_id": family_id,
                    "version_no": 1,
                    "name": name,
                    "description": "Synthetic capacity benchmark record",
                    "source": {"origin": "internal", "author": "benchmark"},
                    "status": "APPROVED",
                    "risk_level": "benign",
                    "vetting": None,
                    "allowed_tools": [],
                    "declared_tools_valid": True,
                    "signature": None,
                    "submitted_at": now,
                    "updated_at": now,
                    "approved_at": now,
                    "approved_by": "benchmark",
                },
                separators=(",", ":"),
            )
            family_rows.append((family_id, name, name, "Synthetic capacity benchmark record", skill_id, skill_id, now, now))
            skill_rows.append((skill_id, name, "APPROVED", "benign", now, now, payload))
        started = time.perf_counter()
        connection.executemany(
            "INSERT INTO skill_families(family_id, normalized_name, name, description, latest_version_id, latest_trusted_version_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            family_rows,
        )
        connection.executemany(
            "INSERT INTO skill_registry(skill_id, name, status, risk_level, submitted_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            skill_rows,
        )
        connection.commit()
        insert_seconds = time.perf_counter() - started
    else:
        insert_seconds = 0.0

    queries = {
        "page_first": (
            "SELECT f.family_id, s.skill_id, s.name, s.status, s.updated_at FROM skill_families f JOIN skill_registry s ON s.skill_id=f.latest_version_id ORDER BY s.updated_at DESC LIMIT 20 OFFSET 0",
            (),
        ),
        "page_middle": (
            "SELECT f.family_id, s.skill_id, s.name, s.status, s.updated_at FROM skill_families f JOIN skill_registry s ON s.skill_id=f.latest_version_id ORDER BY s.updated_at DESC LIMIT 20 OFFSET ?",
            (args.count // 2,),
        ),
        "search_exact": (
            "SELECT f.family_id, s.skill_id, s.name FROM skill_families f JOIN skill_registry s ON s.skill_id=f.latest_version_id WHERE lower(s.name) LIKE ? LIMIT 20",
            (f"%capacity-bench-{args.count - 1:08d}%",),
        ),
        "dashboard_group": (
            "SELECT s.status, s.risk_level, count(*) FROM skill_families f JOIN skill_registry s ON s.skill_id=f.latest_version_id GROUP BY s.status, s.risk_level",
            (),
        ),
    }
    results = {}
    for name, (sql, parameters) in queries.items():
        samples = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            connection.execute(sql, parameters).fetchall()
            samples.append((time.perf_counter() - started) * 1000)
        results[name] = {
            "p50_ms": round(percentile(samples, 0.50), 3),
            "p95_ms": round(percentile(samples, 0.95), 3),
            "mean_ms": round(statistics.fmean(samples), 3),
        }
    total = connection.execute("SELECT count(*) FROM skill_families").fetchone()[0]
    connection.close()
    output = {
        "synthetic_skills_requested": args.count,
        "total_skill_families": total,
        "insert_seconds": round(insert_seconds, 3),
        "database_size_mib": round(db_path.stat().st_size / 1024 / 1024, 2),
        "iterations": args.iterations,
        "queries": results,
    }
    Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="/app/runtime/sqlite/benchmark.db")
    parser.add_argument("--count", type=int, default=50000)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--output", default="/bench/capacity-results.json")
    main(parser.parse_args())
