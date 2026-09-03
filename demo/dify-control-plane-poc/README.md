# Dify control-plane inventory POC

This read-only POC parses a Dify application DSL exported as YAML. It inventories configured workflow nodes,
prompt locations, tools, and knowledge-base identifiers. It does not call Dify, read knowledge documents, inspect
tool implementations, or prove that a configured node ran.

The `agent_profile` section exposes the application name, creation time, description, mode, author, tags, and intent
with a source and collection status for every field. Dify DSL and the public `GET /info` application API do not expose
creation time. Dify also has no standard declared-intent field, so the collector returns these fields as unavailable or
unverified instead of deriving them from a filename, local file timestamp, or an unsupported guess. A later analyzer
may add an inferred intent only when it also records its evidence and confidence separately from declared facts.

Run against the synthetic fixture:

```bash
uv run python scripts/dify-control-plane-poc.py demo/dify-control-plane-poc/example-app.yml
```

Prompt text is omitted by default; the result includes its length and SHA-256 hash. To inspect prompt text in a
controlled terminal, explicitly add `--include-prompt-text`. Do not redirect that output to ordinary application
logs or attach it to unrestricted scan reports.

For a real application, export its DSL from Dify and pass the local YAML path to the same command. A successful
inventory proves only that the selected configuration is represented in that export. Dify control-plane API access,
knowledge-document access, and runtime trace correlation require separate read-only credentials and version-specific
validation.
