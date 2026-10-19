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

## Page API query costs

`BENCHMARK_ISOLATED=YES uv run python tests/performance/benchmark_page_queries.py --output /tmp/page-queries.json`

This separate harness measures nine page API paths against a new temporary SQLite
database: 100 clients, 100 Agents, 1,000 installed Skills, 50,000 client events,
50,000 logs, 50,000 Hooks, 1,000 trace events with 64 KiB synthetic raw payloads,
and 100 completed scan tasks. It records 30 warm request samples per path after
two warmups, SQL counts, response sizes, source hashes and pre-request host state.
`--source-root` selects a frozen application snapshot for matched comparisons.
Temporary databases are removed after the run; the output JSON retains measurements.
Authentication dependencies use a synthetic administrator; route permission checks
remain active. The Skill registry summary is empty. These are in-process TestClient
API timings, without browser rendering, network transfer, collection, audit or
cleanup concurrency. Use the AIDR mixed-load harness below for that separate claim.
See [the page query comparison](../../docs/benchmarks/2026-10-17-page-queries.md).
The [three-pair repeat](../../docs/benchmarks/2026-10-18-page-queries.md) retains the same harness and
fixtures under the user's accepted background load, with full-run CPU/memory/swap observations.

## AIDR collection, outage replay and retention

```bash
BENCHMARK_ISOLATED=YES uv run python tests/performance/benchmark_aidr_concurrency.py
# Matched replay control, without retention during the measurement:
BENCHMARK_ISOLATED=YES uv run python tests/performance/benchmark_aidr_concurrency.py --cleanup-start disabled
# Driver upload limit; generation remains 100 clients / 400 records/s:
BENCHMARK_ISOLATED=YES uv run python tests/performance/benchmark_aidr_concurrency.py --upload-concurrency 4
# Lower offered load: 100 clients, 100 records/s, each gateway at 1 request/s:
BENCHMARK_ISOLATED=YES uv run python tests/performance/benchmark_aidr_concurrency.py --upload-concurrency 4 --batch-seconds 20 --gateway-rps 1
```

The script creates its own temporary directory, fixed source snapshot, backend
database, Registry, license state/signing identity and credentials. It binds the
backend and deterministic upstream to loopback on automatically selected ports;
there is no option to target an existing service or database. Child processes are
terminated and plaintext benchmark credentials removed on exit. Synthetic data,
source manifest, backend logs, `requests.jsonl` and `result.json` remain in the
printed temporary directory for inspection.
Use `--source-root <previous-temporary-directory>/source` to repeat against the
same application snapshot while using the current harness. Source manifests
identify the exact tested files. Child processes explicitly bypass environment
and macOS system proxies for the local upstream. A watchdog captures Python
thread stacks when the backend event loop cannot tick for five seconds.

Defaults: 100 independent client credentials, 10 log records and 10 Hook records
per client every 5 seconds (400 records/s total), 1,024-byte synthetic content per
record, and 5 requests/s each to the model gateway, MCP gateway and direct mock
upstream. Each client has one sequential uploader; clients upload concurrently.
Both gateways perform real authentication, license checks and database writes.
`--upload-concurrency` bounds total emulator uploads (default 100), independently
of backend admission. The current backend shares two asynchronous admission slots
for log and Hook persistence, background Skill audit, overview projection and
each bounded AIDR retention step. The shared semaphore
reserves released slots for queued work; each upload ACK follows its durable commit.
Keep the driver limit identical within each A/B pair.
The upstream sleeps 50 ms per HTTP request. MCP performs its normal multi-request
handshake. The model privacy/PII policy is disabled for this experiment.

The timed phases are gateway baseline (20 s), steady collection (30 s), simulated
outage (20 s), replay plus cleanup (60 s), and continued collection (20 s).
Generation continues during the outage while upload dispatch pauses; in-flight
requests may finish. Frozen batches are flushed/fsynced to a local outbox. A
successful ACK is deliberately ignored on every tenth batch to check byte-for-byte
replay. This emulates transport loss and durable client queues; it does not run the
native Go client or physically disconnect a network interface.

Before measurement, the script inserts and projects 10,000 historical rows each
for logs, Hooks, operations, Pipeline Trace and Runtime Trace events. Only the
first start of production retention loops is gated until replay begins;
their cleanup implementations, batch limits and subsequent scheduling are intact.
This intentionally forces overlap, rather than measuring the normal startup/idle
timer. `--cleanup-start disabled` leaves historical rows untouched as a control.
Request-lease expiry maintenance, when present in the tested source, uses the
same gate; report it separately from the three historical-data cleanup tasks.

Gateway requests use fixed-rate scheduling independent of responses; results
include scheduling lag and latency from intended dispatch time. Upload results
also include age until durable ACK, retry/error counts, final database row counts,
remaining outbox files, cleanup timings, CPU/RSS and database/WAL file sizes.
The run has a bounded final drain (120 s). A generated record is considered
delivered only after a matching durable ACK; always inspect `integrity`,
`drain_complete`, per-channel errors and historical cleanup counts before drawing
capacity conclusions. File sizes are not disk IOPS or SQLite lock-wait measurements.

Recorded gateway lease/Session fixes and the matching 100-client before/after
results are documented in [the gateway pool comparison](../../docs/benchmarks/2026-10-15-gateway-pool-fix.md).
The follow-up investigation of SQLite writer contention, maintenance costs and
MCP transport reuse is documented in [the contention comparison](../../docs/benchmarks/2026-10-15-gateway-contention-fix.md).
Grouped MCP lease transactions and batch ingestion SQL are covered by the
[transaction comparison](../../docs/benchmarks/2026-10-15-gateway-transaction-fix.md),
including a fresh rebased baseline, three matched 100-client profiles and the
additional reverse-order low-load pair. Retain both low-load repetitions when
interpreting the tail-latency results.

Writer-wait diagnostics, grouped model completion transactions, async ingestion
admission and batched overview projections are covered by the
[tail stability comparison](../../docs/benchmarks/2026-10-15-gateway-tail-stability.md).
It retains three fresh low-load pairs and both high-load upload-concurrency
profiles, with exploratory admission variants recorded separately.

Compiled text validation and fixed ingestion SQL caching are covered by the
[backlog comparison](../../docs/benchmarks/2026-10-16-gateway-backlog-fix.md).
It repeats three low-load pairs and two pairs each at 4 and 100 upload slots.
Compare replay-window backlog separately from final drain, and report high-load
gateway regressions alongside collection gains. These runs retain two backend
ingestion slots, independent batch commits and the existing cleanup schedule.

Retention/upload interleaving, optional trace failure and MCP scan finalization
repairs are covered by the [correctness regression comparison](../../docs/benchmarks/2026-10-16-gateway-regression-fixes.md).
It retains all 14 final-source runs, with host CPU/page-in observations and separate
correctness and performance conclusions. Final drain success does not establish
unchanged replay throughput or gateway tail latency.

On macOS, distinguish page-ins from swap-ins when collecting host diagnostics.
The installed psutil 7.2.2 implementation reports `Pageins/Pageouts` through
`swap_memory().sin/sout`. Use the separate `Swapins/Swapouts` counters from
`vm_stat`, multiplied by its reported page size, to measure swap traffic. Retain
page activity separately; neither counter alone attributes stalls to SQLite.

The follow-up [four-upload environment comparison](../../docs/benchmarks/2026-10-16-high4-environment.md)
keeps application source and workload fixed, records separate macOS page/swap
counters, and repeats three alternating pairs after host resource controls.
It includes preflight checks, external process CPU observations and upload-slot
occupancy estimates; distinguish backlog recovery from gateway tail stability.

Add `--diagnostics` for an investigative run to record database-phase duration,
worker queue/execution time, SQL statements taking at least 5 ms (verb/table only),
and HTTP transport exception types/OS error numbers in `diagnostics.jsonl`.
It also records all shared-worker admissions, SQL counts inside write
transactions, and shared AIDR admission wait/active counts when that API is present
in the tested revision. Admission wait, thread queueing and writer acquisition
are distinct stages and must be reported separately.
The probe also measures connection-pool checkout, physical commit time, writer
acquisition and complete writer hold through physical commit/rollback completion.
The existing `write_transaction` field ends before commit; `writer_hold` includes
commit and carries the acquiring operation's `owner`. `initial_writers` records
owner markers observed when acquisition starts, not exact attribution of the whole
wait. Marker removal follows physical release, so transient overlapping markers
do not imply simultaneous SQLite writers. In diagnostic runs only, it issues `BEGIN IMMEDIATE` immediately
before the first implicit DML write, separating acquisition from SQL execution;
this changes transaction instrumentation and must not be enabled for formal A/B
results. Explicit `BEGIN IMMEDIATE` calls remain visible as SQL timings. CPU time
uses the executing thread's clock; wall time includes scheduling and I/O.
Cleanup phases are labeled separately for AIDR, Runtime Trace, Pipeline Trace
and request leases. Other background database work carries its callable name,
including overview projection, so its writer time is not attributed to cleanup.
It records no SQL parameters, request bodies or credentials. Instrumented runs
have extra overhead; use uninstrumented runs for the formal performance matrix.
The workload keeps production maintenance implementations and scheduling, so
report any maintenance batch or scheduling changes when comparing revisions.

Add `--skill-audit` to exercise Skill certification and authenticated page queries.
It seeds ten genuinely signed registry Skills and ten pending usages per client;
every `--skill-every 20` tool-call pairs in each log/Hook stream carries Skill file
evidence. Production certification, signature verification, maintenance cadence
and thirty-second refresh policy remain active. Each of the Skill-use list and
dashboard endpoints receives `--page-rps 1` request/second across the clients.
The list responses must contain the expected certified seed usages. Resource
snapshots include due/unchecked Skill usages and the oldest due age; periodic
rechecks mean that zero overdue work is not the same as an empty audit table.
Maintenance duration/errors are recorded in `skill-maintenance.jsonl`.
Use identical options for both source snapshots. With `--diagnostics`, writer
acquisition and time from acquisition to commit/rollback invocation are labeled
for Skill audit and page requests; commit I/O is measured separately. Diagnostic
runs alter transaction acquisition and must remain separate from formal A/B runs.

The [Skill transaction comparison](../../docs/benchmarks/2026-10-16-skill-audit-transactions.md)
records this mixed workload, two eligible pairs per load level, the retained
environment-affected pair, and separate writer-wait diagnostics. It distinguishes
collection gains from unresolved periodic audit backlog and page tail latency.

The [evidence-query and audit catch-up comparison](../../docs/benchmarks/2026-10-17-aidr-evidence-catchup.md)
repeats the same mixed workload with three eligible pairs per load level. Audit
backlog improves, while collection throughput and page/gateway tail latency do
not establish overall performance acceptance. It includes durable ACK and
concurrency regression checks after the measurements.

The [audit writer and shared-admission comparison](../../docs/benchmarks/2026-10-17-aidr-shared-admission.md)
records the final three paired runs per load, separate lock diagnostics, and a
reproduced slot-handoff race. High-load collection and Skill-list medians improve,
while low-load page latency and some gateway tails remain unresolved. It retains
the exploratory measurements separately from the final-version aggregate.

The [current mixed-load writer diagnosis](../../docs/benchmarks/2026-10-18-aidr-write-hotspots.md)
establishes three runs per load for the current page-optimized baseline and a
separately frozen candidate. It attributes AIDR cleanup and overview projection
writer time independently. The candidate did not meet collection/page acceptance;
final application code remains at the measured baseline. Formal results exclude
instrumented runs and retain all environment-qualified unfavorable samples.

The [retention UPDATE cost analysis](../../docs/benchmarks/2026-10-18-aidr-retention-cache.md)
adds isolated index/cache experiments, twelve alternating mixed-load runs and two
separate diagnostic runs. The temporary-cache candidate shortened retention but
failed overall acceptance because of high-load gateway and periodic-audit tails;
it was withdrawn. Final application hashes match the starting snapshot. The report
separates measured SQL work, pre-commit write time, commit cost and writer waits,
and retains all unfavorable runs alongside the correctness checks.

The [overview and writer-wait comparison](../../docs/benchmarks/2026-10-18-overview-writers.md)
retains lock-free preparation with transactional revalidation and shared admission
for projection/retention. Three qualified pairs per load improve collection backlog
and major gateway medians, while some page pairs worsen and cleanup completes later.
Acceptance is partial. A full environmental pair is excluded transparently and
replaced; separate diagnostic runs check projection lag, expiry and counter integrity.
