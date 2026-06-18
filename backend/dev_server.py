"""Development server entry point with safe reload directories."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the admin backend in development mode.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=True,
        reload_dirs=[
            str(base_dir / "backend"),
            str(base_dir / "agent_manager"),
        ],
    )


if __name__ == "__main__":
    main()
