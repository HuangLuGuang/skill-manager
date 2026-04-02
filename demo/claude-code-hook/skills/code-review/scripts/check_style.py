#!/usr/bin/env python3
"""Check code style and return results."""

import sys

def check_style(code: str) -> dict:
    issues = []
    lines = code.split('\n')

    for i, line in enumerate(lines, 1):
        if len(line) > 100:
            issues.append(f"Line {i}: exceeds 100 characters")
        if line.endswith(' '):
            issues.append(f"Line {i}: trailing whitespace")

    return {"issues": issues, "count": len(issues)}

if __name__ == "__main__":
    # Read code from stdin or argument
    code = sys.stdin.read() if not sys.argv[1:] else sys.argv[1]
    result = check_style(code)
    print(result)