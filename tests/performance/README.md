# Isolated performance benchmark

These scripts reproduce the bounded benchmark documented in
`docs/performance-benchmark.md`. They create credentials, Skills, audit rows, and
up to 50,000 synthetic Registry records, so they must run only against a disposable
Backend, SQLite database, Registry, and Sandbox.

Every mutating or load-generating script requires:

```bash
BENCHMARK_ISOLATED=YES
```

Do not point the scripts at a production URL or mount a production SQLite/Registry
volume. `mock_upstreams.py` provides deterministic OpenAI-compatible and MCP
responses; `seed_isolated_benchmark.py` seeds the disposable stack;
`run_isolated_benchmark.py` records gateway, scan, and runtime-verification results;
and `benchmark_skill_capacity.py` inserts synthetic catalog metadata.

Raw results from the 2026-08-13 run are checked in under `docs/benchmarks/`.
