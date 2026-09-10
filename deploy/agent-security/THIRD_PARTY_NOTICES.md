# Agent Security Third-Party Baseline

This file records the third-party components approved for the Agent Security implementation baseline. It is not evidence that the planned source has already been copied into a release image.

## Tencent AI-Infra-Guard

- Version: `v4.6.0`
- Commit: `e8931cc68001b66ad024fd87ef07394e9e96524a`
- License: Apache License 2.0
- Planned reuse: `agent-scan` and `mcp-scan` inside an isolated Agent Manager Worker image.
- Required product attribution: **Based on Tencent Zhuque Lab AI-Infra-Guard**
- Original repository: <https://github.com/Tencent/AI-Infra-Guard>

When AI-Infra-Guard code is first copied or packaged, the release must also include its unmodified `LICENSE` and `NOTICE` files. Modified upstream files must carry modification notices. Phase 1 must generate an SBOM and review the resolved licenses of all transitive Python dependencies before the Worker image is accepted.

Direct Python dependencies declared by the locked source are recorded in `upstreams.lock.json`. They are an inventory, not a legal conclusion about transitive dependencies.

## DeepSeek Harness

- Reference version: `dsh-v0.1.2-alpha.1`
- Commit: `cd5ef8148158c3a752a658978873241fdf8e2bbc`
- License: MIT
- Use: architecture and interaction reference only.
- Original repository: <https://github.com/deepseek-ai/deepseek-harness>

No DeepSeek Harness package or source is included as a runtime dependency in the P0 baseline. If a later change copies a substantial portion of its source, the MIT copyright and permission notice must be included with that distribution.
