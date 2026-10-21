"""Fail startup if a configured adapter cannot load; Python otherwise ignores this error."""
import os
import sys

if os.environ.get("AM_DIFY_CONFIG"):
    try:
        from am_dify_runtime.hooks import install
        install()
    except Exception:
        sys.stderr.write("dify_runtime.bootstrap_failed\n")
        os._exit(78)
