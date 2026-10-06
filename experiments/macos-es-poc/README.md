# macOS Endpoint Security minimum PoC

实机结果：[基础 PoC 验收](ACCEPTANCE.md)；[真实 Agent 归因验收](AGENT_ACCEPTANCE.md)；[已运行 Agent 只读发现验收](OBSERVATION_ACCEPTANCE.md)；[连续只读归属验收](CONTINUOUS_ACCEPTANCE.md)；[故障与 30 分钟稳定性验收](STABILITY_ACCEPTANCE.md)。Codex 已通过受控启动与真实文件阻断测试；Claude 已确认进程归因，文件工具测试尚未通过，最新服务调用状态见只读发现验收记录。只读发现路径不把快照写入授权归因表。

This isolated experiment observes process `fork`, `exec`, and `exit` events and applies one narrowly scoped `AUTH_OPEN` policy. It denies opens only when both conditions match:

1. the process instance was established by an `exec` notification for the exact canonical `build/file-probe` path, including PID and audit-token PID version;
2. the opened file is the exact canonical temporary protected-file path supplied at startup.

All other opens receive `UINT32_MAX`. Every authorization response uses `cache=false`. The callback responds before it queues JSON logging on a separate bounded serial queue. It performs no network, database, or model calls. The PoC does not call `es_clear_cache`, because that API affects all ES clients and a new client already starts with an empty cache.

## Prerequisites

- macOS 13 or later and an SDK providing the Endpoint Security headers and `libEndpointSecurity`.
- An executable signed with the `com.apple.developer.endpoint-security.client` entitlement. The included target creates an ad-hoc signed development artifact for local testing while SIP is disabled; production distribution with SIP enabled requires Apple's entitlement approval and the corresponding signing/provisioning setup.
- Full Disk Access for the signed monitor and root privileges to create the ES client.

Disabling SIP does not grant the Endpoint Security entitlement or Full Disk Access. Do not change SIP or privacy settings for this experiment.

## Build and sign

Compile first:

```sh
make clean all
```

Create and inspect the entitlement-bearing ad-hoc signature used by this local PoC:

```sh
make adhoc-sign
make inspect-signature
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/macos-es-poc.XXXXXX")
chmod 0700 "$tmpdir"
printf 'protected\n' > "$tmpdir/protected.txt"
./build/es-monitor --enforce ./build/file-probe "$tmpdir/protected.txt" "$tmpdir/ready" "$tmpdir/bound"
```

`es_new_client` reports the actual missing local prerequisite at runtime. Do not infer entitlement, privacy, or privilege success from a successful build. Never put certificate material in this repository.

## Run the bounded acceptance test

After signing and granting the signed monitor Full Disk Access, run from an interactive local terminal:

```sh
sudo ./run-test.sh
```

Build as the normal user; only the test run is elevated. The script requires a real `sudo` invocation, uses a fresh private `mktemp` directory, waits at most 10 seconds for monitor readiness, and uses an explicit marker handshake after the exact PID/PID-version binding. It runs exactly 100 protected and 100 allowed opens, proves `/bin/cat` can read the same protected file, terminates the monitor with a bounded wait, then uses a new `file-probe` instance to prove the file is readable after monitor exit. It verifies correlated fork/exec/exit events and zero response/logging errors. Evidence is returned to the invoking user's ownership; the synthetic test files and markers are removed before PASS.

Expected success line:

```text
PASS target_denies=100 target_allows=100 non_target_read=success post_exit_probe_read=success lifecycle=correlated
```

To run without any authorization events, use observe-only mode with a private readiness path:

```sh
tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/macos-es-observe.XXXXXX")
chmod 0700 "$tmpdir"
sudo ./build/es-monitor --observe "$tmpdir/ready"
```

The acceptance validator parses JSON values rather than matching text. It requires the exact target PID, the exec/exit/auth PID version, the script as lifecycle parent, 100 successful deny responses with positive deadline margin, and a clean monitor summary. Fork PID version is deliberately not equated with the post-exec instance version.

## Manual cleanup

If the terminal is interrupted, `run-test.sh` attempts to stop only the monitor PID it started and removes only files in its fresh temporary directory. Check and clean a retained evidence directory with:

```sh
pgrep -fl '/macos-es-poc/build/es-monitor'
rm -rf /private/var/folders/.../macos-es-poc.XXXXXX
make clean
```

Resolve and inspect the exact temporary path printed by the script before removing it. The experiment installs no daemon, launch item, system extension, kernel extension, network service, or persistent policy.

## Registered Agent attribution experiment

`inspect_agent_entrypoints.py` reports only executable entry paths and versions; it does not read authentication data. Agent enforcement never registers a process by its name. `agent-launcher` must be explicitly started with the monitor's single-use per-run nonce; this nonce coordinates the test and is not an authentication credential. Its exact exec instance becomes `direct`; forked children become `inherited`; unrelated processes remain `unknown`. An exec transition migrates attribution only from the exact old PID/PID-version instance supplied by ES. The log also proves that the attributed chain reached the configured native Agent entry. Parent exit does not erase live descendants, while exit of an exact instance removes it. These labels establish process ancestry only; they do not claim a model session, tool call, user, or semantic action.

The PoC uses a fixed 4096-entry in-memory table with linear lookup. Capacity or transition gaps become `unknown`, increment the attribution gap counter, and fail acceptance. This is not a production-scale completeness claim.

Run local state-machine and evidence tests without privilege or network access:

```sh
make clean all
./build/test-attribution
/usr/bin/python3 -B -m unittest discover -v -p 'test_*.py'
./inspect_agent_entrypoints.py
```

After source review, a privileged operator can run one isolated real CLI test. Each command creates synthetic files in a new temporary directory, runs the CLI as the invoking non-root user, preserves existing authentication, and limits the prompt to one Bash read command. Codex disables user rules/config and uses an ephemeral read-only sandbox; Claude uses safe mode, no session persistence, and only the Bash tool. Each invocation has a three-minute timeout.

```sh
make adhoc-sign
sudo ./run-agent-test.sh claude
sudo ./run-agent-test.sh codex
```

If the current shell requires network proxies, preserve only the required proxy variables for the test, as in the recorded run: `sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,ALL_PROXY ./run-agent-test.sh codex`. Agent stdout and diagnostic stderr are stored separately. The script consumes explicit authentication failures as a blocked run, cleans up, and returns exit status 77.

The script validates an attributed ES denial of `protected.txt`, an allowed-file marker in actual CLI output, a successful ordinary-terminal read of the protected file, clean monitor exit, and private-fixture cleanup. It never registers or blocks already-running Claude, Codex CLI, or Codex Desktop processes.

## Read-only discovery of installed and running Agents

`observe_agents.py` catalogs installed Claude Code, Codex CLI, Claude Desktop, and the Codex components shipped in `ChatGPT.app`. It distinguishes CLI entry scripts, native CLI/backend executables, GUI processes, Electron helpers, and `codex-code-mode-host`. GUI, helper, and tool-host components are never ancestry roots; only the exact cataloged native CLI/backend paths can root an inferred snapshot tree.

The catalog records the canonical path, filesystem device/inode, bundle version, and metadata printed by `codesign -d`. The field `verification=not_performed` is intentional: this is component discovery, not signature verification or an authentication decision. An exact matching process receives `identity_basis=catalog_path_match`; a same-name executable elsewhere does not match. An inferred child uses `snapshot_ppid_chain`, `component_role=unclassified_descendant`, and `root_candidate=false`; its root's component type is separate in `root_component_role`.

Process collection uses `libproc` only. For each PID it reads `PROC_PIDTBSDINFO`, `proc_pidpath`, and then both values again. Records that disappear or change are omitted with an error count. The stable key is PID plus process start time in microseconds. The collector never reads process arguments, environments, prompts, credentials, or customer file contents. It bounds the process count, process-read duration, classification work, sample count, and interval; helper and package scans use per-directory result limits. The duration option applies to process sampling, not the entire installation scan. JSON coverage says `complete`, `partial`, or `unavailable` and reports read failures and detected races; `identity_unavailable` alone does not establish whether permission denial or process exit caused the failure.

Run one bounded snapshot as the current user; root and Full Disk Access are not required:

```sh
/usr/bin/python3 -B ./observe_agents.py > observation.json
```

`snapshot` means the executable path exactly matched one catalog component during this sample. `inferred` means the complete, currently visible PPID chain led to a cataloged native root and every parent was older than its child. If a parent has exited, a PID conflicts, a read is denied, the budget is exhausted, or the chain is incomplete, no ancestry claim is emitted. These labels do not mean Endpoint Security `direct`/`inherited`, and do not identify a session, turn, user intent, or tool call.

The snapshot is not atomic. Double reads reject common PID-reuse and exec races, but cannot rule out an ABA transition. It therefore cannot initialize the authorization attribution table. The separate continuous observer below keeps startup snapshot candidates separate until a version-gated ES event provides a stable bridge: `es_process_t.start_time` requires message version 3 and `parent_audit_token` requires version 4. Events that cannot be bridged remain `unknown`; PID alone never grants authority.

### Real, zero-model-call observation test

The acceptance driver starts the installed native Claude Code and Codex CLI binaries with only `--version`. `snapshot-launcher` uses `POSIX_SPAWN_START_SUSPENDED`, allowing the collector to prove the exact child identity before release. Both handshake and runtime have watchdogs; INT, TERM, HUP, timeout, or protocol failure kill and reap only that launcher-owned child. It does not inspect or signal any existing Agent or desktop process.

```sh
make all
/usr/bin/python3 -B -m unittest -v test_snapshot_attribution.py test_snapshot_launcher.py
/usr/bin/python3 -B ./run_observation_test.py > real-observation.json
```

The pure fixture suite covers same-name spoofing, path changes, PID reuse at both different and identical Agent paths, duplicate PID records, multiple roots, parent exit, missing snapshots, permission-style omission, helper non-root behavior, launcher spawn failure, interrupted handshake, parent termination, and child runtime timeout. Fixture success does not replace the two suspended real-binary observations in `run_observation_test.py`.

## Continuous read-only ES attribution

`es-continuous-observer` is separate from `es-monitor`; it subscribes only to `NOTIFY_FORK`, `NOTIFY_EXEC`, and `NOTIFY_EXIT` and has no authorization-event subscription or deny path. The existing AUTH PoC does not import its state.

The observer accepts `--duration` from 1 through 86400 seconds. Event callbacks only copy into the 8192-entry event ring. JSON serialization runs in bounded consumer batches with a per-event autorelease pool. Serialized records enter a separate 1024-record, 16 KiB-per-record queue and pass through a nonblocking internal pipe to an isolated writer process. The writer's buffer is allocated before `fork`; after `fork` it uses only the inherited read/write/close/exit path. Slow stdout, `EPIPE`, and ordinary write failures therefore do not block the ES callback or attribution loop.

Shutdown gives log delivery two seconds, then terminates a stuck writer and uses a second bounded reap window. A log queue overflow, write error, writer timeout, ES ring overflow, sequence fault, or remaining event produces degraded coverage and exit status 74. Snapshot partial coverage alone does not fail the observer. `stderr` carries one final diagnostic line and is supported only when redirected to a normal file, as the supplied drivers do; an arbitrarily blocked stderr pipe is outside this PoC contract.

The final `SUMMARY` exposes `received`, `enqueued`, `processed`, `event_discarded`, `ring_high_water`, `event_remaining`, `log_enqueued`, `log_written`, `log_unconfirmed`, `log_dropped`, `log_errors`, `log_high_water`, `log_remaining`, and `log_shutdown_timeout`, alongside coverage, epoch, gap, overflow, and snapshot fields. On event-ring overflow, the consumer invalidates attribution and discards the buffered history so an older exec cannot recreate state after a lost exit; `event_discarded` counts those buffered records separately from rejected arrivals. `log_unconfirmed` is `log_enqueued - log_written`; if the writer exits without a valid status, it reports records whose final delivery cannot be established rather than claiming they were definitely lost. A healthy exit requires it to be zero. Unconfirmed and dropped counts can overlap and must not be summed as distinct losses.

After subscribing, the observer creates the ready marker and immediately takes a bounded `libproc` snapshot while callbacks copy events into a fixed 8192-entry ring. The callback does no JSON serialization or blocking output. After the snapshot it drains the events in their original arrival order, with the number already queued at the snapshot boundary marked `replay=true`; later arrivals are not called replay events. Processing and shutdown use bounded batches.

Each observer owns a new in-memory state and session UUID; it does not import events or state from another session. Within that state, the key is PID, audit-token PID version, and ES fork start time. Snapshot candidates lack PID version and remain candidates. A candidate is promoted only by an ES fork generated after that candidate's final snapshot read, whose actor has the same PID, fork start time, complete executable path, and a child `parent_audit_token` equal to the actor audit token. An ES exec of a catalog path can independently establish a root. Exec migrates an already confirmed ancestry to the new PID version even when the target is a shell or other non-Agent binary. Exit removes only the exact instance; parent exit does not erase a live descendant.

Message version 4 is required so the observer has v3 start time, v4 parent audit token, and v4 global sequence. Each record includes event-type sequence, global sequence, message version, Mach time, wall time, before/after identities, path-completeness flags, attribution, root identity, coverage epoch, and monitor session. Zero is accepted as an initial sequence value. A sequence gap, duplicate, out-of-order delivery, invalid parent link, truncated executable path, table exhaustion, or ring overflow clears confirmed state and candidates. Later ES events may independently establish new state, but missing-history edges are not restored.

Snapshot coverage and ES-stream coverage are reported separately. Snapshot read failures make `snapshot_coverage=partial`; they do not assert an ES event gap. `coverage=complete` means only that the events visible for this client's current three subscriptions were sequential and fit within this PoC's buffers. Endpoint Security default muted paths and event types are left unchanged, so this is not a claim of complete system activity or bypass resistance. Catalog path matching is product-component observation, not code-signature authentication. Process ancestry still says nothing about session, turn, prompt, or tool semantics; both semantic fields remain `unknown`.

Local state-machine validation requires no privilege:

```sh
make all
./build/test-continuous-state
./run-continuous-fault-tests.sh
```

The local fault script is test-only. Synthetic state-machine records are labeled `source=test_injection` and never enter the production observer. It covers queue ordering and overflow barriers, gaps, duplicates, out-of-order delivery, repeated exec, parent exit, PID-version reuse, and restart isolation. The output tests exercise a blocked real pipe, a real-pipe `EPIPE`, and a test-build write seam that makes the writer's actual output call return `ENOSPC`; they also verify bounded shutdown and idle writer death. Production binaries expose no fault-injection or snapshot-hold option.

The privileged fault acceptance builds separate test-only observers from the same event ring and consumer source. Their compile-time startup hold lets real ES events accumulate before snapshot completion; one build verifies boundary replay and the other uses a four-entry ring to exercise the actual overflow barrier. Those records retain `source=es_notify`, while the snapshot record explicitly carries `test_only`, `test_mode`, and the hold budget. These binaries are not part of `make all`:

```sh
make fault-sign
sudo ./run-es-fault-tests.sh
```

After building and reviewing the sources, sign the observer and run the bounded real test:

```sh
make adhoc-sign
sudo ./run-continuous-observation-test.sh
```

The script starts its own native fixture before the observer. The snapshot sees the waiting root; after the snapshot boundary the script releases it to fork, exit the parent, exec `/bin/sleep` in the child, and exit the child. It then starts the installed native Claude Code and Codex binaries with only `--version`. The validator correlates exact PIDs, PID versions, start times, root identity, lifecycle order, per-type/global sequences, and the zero-gap/zero-overflow summary. All launched processes and the monitor have watchdogs and cleanup targets only their own process groups. See [the independent acceptance record](CONTINUOUS_ACCEPTANCE.md) for verified results and remaining test gaps.

For a real 30-minute stability run, use the separately bounded driver after signing:

```sh
sudo /usr/bin/python3 -B ./run_stability_test.py --duration 1800 --interval 5
```

It samples the observer plus writer process group, runs a non-model `/usr/bin/true` probe every 30 seconds, caps evidence size, and verifies event/log counters. Its acceptance budgets are one-core average CPU at most 5%, peak RSS at most 256 MiB, and post-warmup median RSS growth at most 16 MiB. This ambient-plus-probe run is a stability check, not a throughput or saturation claim.

The normal signed observer can also be tested against real blocked and broken stdout pipes, followed by SIGINT and SIGTERM cleanup:

```sh
sudo /usr/bin/python3 -B ./run_log_failure_tests.py
```

The driver bounds each case, preserves diagnostic evidence, and verifies that the observer and its writer process group have exited. See [fault and stability acceptance](STABILITY_ACCEPTANCE.md) for the independent measurements and test boundaries.

This remains a local PoC. The snapshot bounds the PID count, both queues have fixed capacity, and the drivers impose outer time and evidence budgets. Actual kernel loss and sustained saturation still require separate production-scale qualification.

## Root relay to an unprivileged Go client

`runtime_observation_relay.py` is a manually started development service. It starts `es-continuous-observer` with its optional heartbeat enabled and exposes a one-way, version 1 newline-JSON feed. It accepts no client commands or policy changes. The authorized user receives system-wide process metadata visible to Endpoint Security; the relay does not filter events by UID.

For the privileged boundary, copy the relay and signed observer into a dedicated root-owned directory whose complete ancestor chain is not group/other writable. Do not run the root relay or observer from this user-writable checkout. The relay also requires a protected observer-stderr path, creates a `0600` socket owned by exactly one authorized UID, checks connecting peer credentials, caps frames at 64 KiB, caps each client queue at 128 frames, and disconnects a slow consumer. A typical manually prepared invocation is:

```sh
sudo /usr/bin/python3 /Library/Application\ Support/AgentManagerRuntime/runtime_observation_relay.py \
  --socket /Library/Application\ Support/AgentManagerRuntime/runtime.sock \
  --allow-uid "$(id -u)" \
  --observer /Library/Application\ Support/AgentManagerRuntime/es-continuous-observer \
  --observer-stderr /Library/Application\ Support/AgentManagerRuntime/observer.stderr \
  --heartbeat 2 --health-timeout 6 --duration 86400 \
  --catalog /Applications/ChatGPT.app/Contents/Resources/codex
```

The ordinary user watches it through the existing client CLI:

```sh
go -C scanner build -o ../experiments/macos-es-poc/build/agent-manager-client ./cmd/agent-manager-client
experiments/macos-es-poc/build/agent-manager-client runtime-watch \
  --socket /Library/Application\ Support/AgentManagerRuntime/runtime.sock \
  --reconnect 1s --health-timeout 5s
```

Run the build/watch commands above from the repository root. Every connection starts with `stream_start=late_join` and `attribution_baseline=unknown`; there is no history replay. Every reconnect emits `reset=true`, requiring consumers to discard connection-local attribution even when the observer session happens to be unchanged. This CLI does not maintain a process-tree cache. `transport` reports socket connectivity, while `observer_health` is driven by the observer heartbeat. A stopped observer becomes `stale` after the configured timeout even if its process remains alive. Helper exit becomes `offline`; restart creates a new monitor session. This PoC does not install launchd configuration or perform production signing.

Independent privileged verification, from this experiment directory after building and signing:

```sh
sudo /usr/bin/python3 -B ./run_runtime_connection_test.py
```

The driver stages root-owned binaries and the relay in a temporary protected directory, runs the existing client as the invoking ordinary user, and removes its processes and deployment directory afterward. See [runtime connection acceptance](RUNTIME_CONNECTION_ACCEPTANCE.md) for evidence and limits. The CLI fails explicitly if its output pipe is full, broken or short-written; consumers should discard a final unterminated JSON line and treat exit as a coverage break.
