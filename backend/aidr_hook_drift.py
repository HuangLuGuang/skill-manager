"""Exact finite comparison of published tool rules, not client effective state."""
import json
import time

from .aidr_hook_control import HookPolicyRow, evaluate


RANK = {"deny": 0, "ask": 1, "allow": 2}


def explain(policy, agent, tool):
    decision = evaluate(policy, agent, tool)
    matches = [r for r in policy["rules"] if r["agent"] in (agent, "*") and r["tool"] in (tool, "*")]
    ids = decision["matched_rule_ids"]
    return {**decision, "matched_rule_ids": ids[:8], "matched_ids_truncated": len(ids) > 8,
            "conflict": len({r["decision"] for r in matches}) > 1}


def compare(previous, current):
    if any(r.get('command') for p in (previous, current) if p for r in p['rules']):
        return dict(code='aidr_hook_policy_command_scoped', previous_revision=previous['revision'] if previous else None,
                    current_revision=current['revision'], counts={}, conflict_partitions=None,
                    partition_count=None, items=[], details_truncated=False, rule_changes={})
    # Exact tool names and the wildcard partition the whole tool namespace.
    # None represents all names absent from BOTH policies, never a tool request.
    names = sorted({r["tool"] for p in (previous, current) if p for r in p["rules"] if r["tool"] != "*"})
    counts = {"expanded": 0, "restricted": 0, "unchanged": 0, "baseline_unknown": 0}
    cells, conflicts = [], 0
    for agent in ("claude", "codex"):
        for tool in [*names, None]:
            after = explain(current, agent, tool)
            before = explain(previous, agent, tool) if previous else None
            if before is None:
                change = "baseline_unknown"
            else:
                delta = RANK[after["decision"]] - RANK[before["decision"]]
                change = "expanded" if delta > 0 else "restricted" if delta < 0 else "unchanged"
            counts[change] += 1
            conflicts += int(after["conflict"])
            if change != "unchanged" or after["conflict"]:
                cells.append({"agent": agent, "tool": tool, "scope": "other_tools" if tool is None else "exact_tool",
                              "change": change, "before": before, "after": after})
    cells.sort(key=lambda c: ({"expanded": 0, "restricted": 1, "baseline_unknown": 2, "unchanged": 3}[c["change"]], c["agent"], c["tool"] or ""))
    old = {r["id"]: r for r in previous["rules"]} if previous else {}
    new = {r["id"]: r for r in current["rules"]}
    return {"code": "aidr_hook_policy_compared" if previous else "aidr_hook_policy_baseline_unknown",
            "previous_revision": previous["revision"] if previous else None,
            "current_revision": current["revision"], "counts": counts, "conflict_partitions": conflicts,
            "partition_count": sum(counts.values()), "items": cells[:64], "details_truncated": len(cells) > 64,
            "rule_changes": {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
                             "modified": sorted(k for k in old.keys() & new.keys() if old[k] != new[k])}}


def policy_analysis(db, client_id, revision):
    rows = db.query(HookPolicyRow).filter_by(client_id=client_id).filter(HookPolicyRow.revision <= revision).order_by(HookPolicyRow.revision.desc()).limit(2).all()
    if not rows:
        return None
    current = json.loads(rows[0].payload)
    previous = json.loads(rows[1].payload) if len(rows) > 1 else None
    return {**compare(previous, current), "evidence_type": "published_policy_comparison",
            "reported_at": str(int(time.time())), "published_by": rows[0].created_by,
            "issued_at": current["issued_at"], "validity": "until_replaced",
            "client_application": "unknown"}
