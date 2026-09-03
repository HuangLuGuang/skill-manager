# Copyright (c) 2024-2026 Tencent Zhuque Lab. All rights reserved.
# Licensed under the Apache License, Version 2.0.

"""Program-controlled execution provenance for Agent Scan detection workers.

Added by Agent Manager to preserve per-skill execution and finding provenance.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from agent_scan.utils.logging import logger


def worker_stage_id(index: int) -> str:
    return f"2{chr(ord('a') + index)}"


def extract_vuln_blocks(text: str) -> list[str]:
    return re.findall(r"<vuln>.*?</vuln>", text or "", re.DOTALL)


def sanitize_worker_error(error: Exception) -> str:
    """Return a bounded diagnostic without credentials or request content."""
    message = re.sub(r"[\r\n\t]+", " ", str(error))
    message = re.sub(
        r"(?i)\b(authorization|cookie|api[-_ ]?key|access[-_ ]?token|token)\b\s*[:=]\s*(?:bearer\s+)?[^\s,;]+",
        r"\1=[REDACTED]",
        message,
    )
    message = re.sub(r"(?i)\b(?:sk|key|token)-[a-z0-9._-]{8,}\b", "[REDACTED]", message)
    return message[:512]


def source_tagged_vuln(block: str, *, source_ref: str) -> str:
    return block.replace("<vuln>", f"<vuln>\n<source_ref>{source_ref}</source_ref>", 1)


def merge_worker_outcomes(
    outcomes: list[Any],
    skill_names: list[str],
) -> tuple[str, dict[str, int], list[dict[str, Any]], dict[str, str]]:
    """Keep an execution record for every selected detection worker."""
    vuln_blocks: list[str] = []
    aggregated_stats: dict[str, int] = {}
    executions: list[dict[str, Any]] = []
    source_map: dict[str, str] = {}

    for idx, outcome in enumerate(outcomes):
        skill_name = skill_names[idx] if idx < len(skill_names) else f"worker-{idx}"
        stage_id = worker_stage_id(idx)
        if isinstance(outcome, Exception):
            logger.warning("Skill worker '%s' failed with %s", skill_name, type(outcome).__name__)
            executions.append(
                {
                    "skill_name": skill_name,
                    "stage_id": stage_id,
                    "status": "error",
                    "dialogue_calls": 0,
                    "finding_count": 0,
                    "error_type": type(outcome).__name__[:128],
                    "error_message": sanitize_worker_error(outcome),
                }
            )
            continue

        result_text, stats = outcome
        worker_blocks = extract_vuln_blocks(result_text)
        for position, block in enumerate(worker_blocks, start=1):
            source_ref = hashlib.sha256(
                f"{stage_id}:{skill_name}:{position}".encode()
            ).hexdigest()[:24]
            source_map[source_ref] = skill_name
            vuln_blocks.append(source_tagged_vuln(block, source_ref=source_ref))
        executions.append(
            {
                "skill_name": skill_name,
                "stage_id": stage_id,
                "status": "completed",
                "dialogue_calls": max(0, int((stats or {}).get("dialogue", 0))),
                "finding_count": len(worker_blocks),
                "error_type": None,
                "error_message": None,
            }
        )
        for tool, count in (stats or {}).items():
            aggregated_stats[tool] = aggregated_stats.get(tool, 0) + count

    merged_xml = "\n\n".join(vuln_blocks) if vuln_blocks else "No vulnerabilities confirmed."
    return merged_xml, aggregated_stats, executions, source_map


def attach_controlled_sources(results: list[dict[str, Any]], source_map: dict[str, str]) -> None:
    """Resolve reviewer-returned opaque refs through the program-owned map."""
    for finding in results:
        source_ref = finding.pop("source_ref", None)
        source_skill = source_map.get(source_ref or "")
        if source_skill:
            finding["source_skill"] = source_skill
            finding["source_mapping"] = "worker_context"
        else:
            finding["source_skill"] = None
            finding["source_mapping"] = "unmapped"
