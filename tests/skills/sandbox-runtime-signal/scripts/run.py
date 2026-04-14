from __future__ import annotations

import os
import sys
import urllib.request


def main() -> int:
    print("sandbox test: attempting network access to https://example.com/forbidden")
    print("sandbox test: API_KEY lookup result:", os.getenv("API_KEY", "missing"))
    print("sandbox test: dynamic execution marker eval")

    try:
        eval("1 + 1")
    except Exception as exc:
        print(f"sandbox test: eval failed: {exc}", file=sys.stderr)

    try:
        urllib.request.urlopen("https://example.com/forbidden", timeout=2)
    except Exception as exc:
        print(f"sandbox test: network failure for https://example.com/forbidden: {exc}", file=sys.stderr)

    try:
        with open("/root/sandbox-write-test.txt", "w", encoding="utf-8") as handle:
            handle.write("should not be writable")
    except Exception as exc:
        print(f"sandbox test: permission denied while writing privileged path: {exc}", file=sys.stderr)

    return 7


if __name__ == "__main__":
    raise SystemExit(main())
