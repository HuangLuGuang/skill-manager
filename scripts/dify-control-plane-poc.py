#!/usr/bin/env python3
"""Inspect an exported Dify DSL without calling or modifying Dify."""

from __future__ import annotations

import argparse
import json

from agent_manager.core.dify_control_plane import collect_dify_dsl_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract prompts, tools, and knowledge-base references from Dify DSL")
    parser.add_argument("dsl", help="Path to a Dify YAML DSL export")
    parser.add_argument(
        "--include-prompt-text",
        action="store_true",
        help="Include raw prompt text in stdout (sensitive; disabled by default)",
    )
    args = parser.parse_args()
    print(json.dumps(collect_dify_dsl_file(args.dsl, include_prompt_text=args.include_prompt_text), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
