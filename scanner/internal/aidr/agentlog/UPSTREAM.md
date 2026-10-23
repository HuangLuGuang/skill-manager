# Upstream review and reuse inventory

- upstream_url: https://github.com/uber/ADR
- commit: fe450694b15d8569952946f9fdae56d80d6dc431
- reviewed_paths: Sensor/adr_sensor/parsers/codex_parser.py; Sensor/adr_sensor/parsers/claude_parser.py; NOTICE.md
- reuse_category: design and format reference only
- imported_files: none
- patches: independent Go implementation; no upstream Python runtime or fixtures included
- local_owner: Agent Manager scanner component
- supported_platforms: macOS real-log acceptance; Windows/Linux compilation only
- tests: agentlog Go regression suite; independent Python shared contract vectors; anonymous local log fixtures; read-only real-source CLI acceptance
- last_reviewed: 2026-09-23

The design's root Apache-2.0 attribution does not replace per-file notices. ADR's NOTICE lists additional third-party obligations. Since no source or fixtures are copied in this delivery, no upstream code/license files are redistributed; any future code adoption must perform the per-file license review and retain the required notices then.

Reference: [Codex parser](https://github.com/uber/ADR/blob/fe450694b15d8569952946f9fdae56d80d6dc431/Sensor/adr_sensor/parsers/codex_parser.py), [Claude parser](https://github.com/uber/ADR/blob/fe450694b15d8569952946f9fdae56d80d6dc431/Sensor/adr_sensor/parsers/claude_parser.py), [NOTICE](https://github.com/uber/ADR/blob/fe450694b15d8569952946f9fdae56d80d6dc431/NOTICE.md).

Local fixtures preserve observed structural fields but replace timestamps, session/turn/call identifiers, inputs and outputs. Tool names and Agent versions are retained. They are not upstream fixtures and do not imply upstream-equivalent coverage.

## Doubao IndexedDB cache

`doubao_leveldb.go` and `doubao_v8.go` are independent, bounded readers for the observed Doubao Work 2.33.3 IM cache. They read WAL/SST records without opening or repairing the database, verify CRC32C, and accept only the named IM state store and Blink v21 / V8 v15 plain-object encoding. The source is the chat database's `CURRENT` marker; one source snapshot consolidates the chat and launcher WebViews. Its cursor offset is a snapshot row index, and the scheduler revisits it periodically. Unsupported encodings leave trajectory ingestion independent.

Format reference: [Chromium IndexedDB wrapping protocol](https://chromium.googlesource.com/chromium/src/+/b62e33f47930b144cb1eb047a4921949a38df024/third_party/blink/renderer/modules/indexeddb/idb_value_wrapping.cc). Snappy decompression uses `github.com/golang/snappy` v0.0.4. No Chromium implementation or real user payload is copied into the repository. `testdata/doubao-cache.bin` contains synthetic plain objects serialized with Node's V8 serializer and a Blink envelope; the Go tests build checksummed WAL/SST fixtures from it.
