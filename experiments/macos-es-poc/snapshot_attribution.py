#!/usr/bin/env python3
"""Pure snapshot classification; it deliberately has no Endpoint Security semantics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, order=True)
class ProcessIdentity:
    pid: int
    start_time_us: int


@dataclass(frozen=True)
class ProcessRecord:
    identity: ProcessIdentity
    ppid: int
    executable: str


@dataclass(frozen=True)
class Component:
    agent: str
    surface: str
    role: str
    path: str
    root_candidate: bool


def canonical(path: str) -> str:
    return str(Path(path).resolve(strict=False))


def classify_snapshot(records: Iterable[ProcessRecord], components: Iterable[Component],
                      diagnostics: dict | None = None, max_work: int = 100_000) -> list[dict]:
    """Classify one instantaneous process tree using exact executable paths.

    Exact component matches are ``snapshot``. A currently visible descendant of a
    root candidate is only ``inferred``. Missing ancestors are never reconstructed.
    PID alone is not an identity and never appears in the lookup key.
    """
    materialized = list(records)
    pid_counts: dict[int, int] = {}
    for record in materialized:
        pid_counts[record.identity.pid] = pid_counts.get(record.identity.pid, 0) + 1
    conflicted_pids = {pid for pid, count in pid_counts.items() if count != 1}
    processes = {record.identity: record for record in materialized if record.identity.pid not in conflicted_pids}
    by_pid: dict[int, list[ProcessRecord]] = {}
    for record in processes.values():
        by_pid.setdefault(record.identity.pid, []).append(record)
    exact: dict[str, list[Component]] = {}
    for component in components:
        exact.setdefault(canonical(component.path), []).append(component)

    results: list[dict] = []
    roots: list[tuple[ProcessRecord, Component]] = []
    exact_identities: set[ProcessIdentity] = set()
    for record in processes.values():
        matches = exact.get(canonical(record.executable), [])
        for component in matches:
            exact_identities.add(record.identity)
            results.append(_result(record, component, "snapshot",
                                   record.identity if component.root_candidate else None, 0))
            if component.root_candidate:
                roots.append((record, component))

    already = {(item["pid"], item["start_time_us"], item["agent"], item["component_role"]) for item in results}
    work = 0
    truncated = False
    for record in processes.values():
        if record.identity in exact_identities:
            continue
        for root, component in roots:
            work += 1
            if work > max_work:
                truncated = True
                break
            distance = _distance(record, root, by_pid, min(len(processes) + 1, 256))
            key = (record.identity.pid, record.identity.start_time_us, component.agent, component.role)
            if distance is not None and distance > 0 and key not in already:
                results.append(_result(record, component, "inferred", root.identity, distance))
        if truncated:
            break

    if diagnostics is not None:
        diagnostics.update({"conflicted_pids": len(conflicted_pids), "work": work,
                            "max_work": max_work, "truncated": truncated,
                            "unmatched_records": len(processes) - len({item["pid"] for item in results})})

    return sorted(results, key=lambda item: (item["pid"], item["start_time_us"], item["agent"], item["component_role"]))


def _distance(record: ProcessRecord, root: ProcessRecord, by_pid: dict[int, list[ProcessRecord]], limit: int) -> int | None:
    current = record
    seen = {current.identity}
    for distance in range(1, limit + 1):
        parents = by_pid.get(current.ppid, [])
        if len(parents) != 1:
            return None
        parent = parents[0]
        if parent.identity.start_time_us > current.identity.start_time_us:
            return None
        if parent.identity == root.identity:
            return distance
        if parent.identity in seen:
            return None
        seen.add(parent.identity)
        current = parent
    return None


def _result(record: ProcessRecord, component: Component, attribution: str,
            root: ProcessIdentity | None, distance: int) -> dict:
    return {
        "pid": record.identity.pid,
        "start_time_us": record.identity.start_time_us,
        "ppid": record.ppid,
        "executable": canonical(record.executable),
        "agent": component.agent,
        "surface": component.surface,
        "component_role": component.role if attribution == "snapshot" else "unclassified_descendant",
        "root_candidate": attribution == "snapshot" and component.root_candidate,
        "root_component_role": component.role if root is not None else None,
        "identity_basis": "catalog_path_match" if attribution == "snapshot" else "snapshot_ppid_chain",
        "attribution": attribution,
        "root": None if root is None else {"pid": root.pid, "start_time_us": root.start_time_us},
        "ancestry_distance": distance,
    }
