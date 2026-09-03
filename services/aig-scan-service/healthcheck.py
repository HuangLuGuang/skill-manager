from __future__ import annotations

import json
import os
import urllib.request


def main() -> int:
    token = os.environ.get("AIG_WRAPPER_TOKEN", "").strip()
    if not token:
        return 1
    request = urllib.request.Request(
        "http://127.0.0.1:8093/healthz",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            body = json.loads(response.read(16_384).decode("utf-8"))
    except Exception:
        return 1
    engine = body.get("engine") if isinstance(body, dict) else None
    return 0 if body.get("status") == "ok" and engine == {
        "name": "AI-Infra-Guard",
        "tag": "v4.6.0",
        "commit": "e8931cc68001b66ad024fd87ef07394e9e96524a",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
