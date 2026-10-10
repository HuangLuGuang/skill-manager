"""Scopes for a discovered installation, using client-reported identities."""

import posixpath


def installation_owns_path(agent: dict, path: str, os: str = "") -> bool:
    def normalize(value):
        normalized = posixpath.normpath(str(value).replace("\\", "/"))
        return normalized.casefold() if os == "windows" else normalized

    if not path:
        return False
    roots = [agent.get("skills_path"), *(agent.get("capabilities", {}).get("skill_roots") or [])]
    candidate = normalize(path)
    return any(candidate.startswith(normalize(root).rstrip("/") + "/") for root in roots if root)
