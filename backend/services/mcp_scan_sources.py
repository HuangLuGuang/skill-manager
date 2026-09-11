"""Immutable, bounded source bundles for MCP audits."""
from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from ..api_errors import ApiError
from ..config import settings

MAX_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
MAX_FILES = 1000
IGNORED = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}


def invalid():
    return ApiError(422, "mcp_scan.source_invalid", "源码包无效、包含不安全路径或超过大小限制", "Source bundle is invalid, contains unsafe paths, or exceeds limits")


def normalize_bundle(content: bytes) -> list[dict]:
    if len(content) > MAX_BYTES:
        raise invalid()
    files, seen, total = [], set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if len(archive.infolist()) > MAX_FILES * 2:
                raise invalid()
            for item in archive.infolist():
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename:
                    raise invalid()
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
                    raise invalid()
                if item.is_dir() or any(part in IGNORED for part in path.parts):
                    continue
                if item.file_size > MAX_FILE_BYTES or len(files) >= MAX_FILES:
                    raise invalid()
                total += item.file_size
                if total > MAX_BYTES or str(path) in seen:
                    raise invalid()
                seen.add(str(path))
                raw = archive.read(item)
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
                if text is not None and "\x00" in text:
                    text = None
                files.append({"path": str(path), "content": text, "sha256": hashlib.sha256(raw).hexdigest()})
    except (zipfile.BadZipFile, RuntimeError, OSError, ValueError) as exc:
        raise invalid() from exc
    if not files or not any(f["content"] is not None for f in files):
        raise invalid()
    # Git archives commonly contain one enclosing directory.
    roots = {f["path"].split("/")[0] for f in files}
    if len(roots) == 1 and all("/" in f["path"] for f in files):
        for item in files:
            item["path"] = item["path"].split("/", 1)[1]
    return sorted(files, key=lambda f: f["path"])


def source_root() -> Path:
    root = Path(settings.DATA_DIR) / "mcp-scan-sources"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def save_source(content: bytes, owner_id: int, *, origin: str, revision: str | None = None) -> dict:
    files = normalize_bundle(content)
    digest = hashlib.sha256(json.dumps(files, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    source_id = hashlib.sha256(f"{owner_id}:{digest}:{origin}:{revision}".encode()).hexdigest()
    record = {"source_id": source_id, "sha256": digest, "owner_id": owner_id, "origin": origin,
              "revision": revision, "file_count": len(files), "files": files}
    path = source_root() / f"{source_id}.json"
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            load_source(source_id)
    finally:
        os.unlink(temporary)
    return {k: v for k, v in record.items() if k != "files"}


def load_source(source_id: str) -> dict:
    if len(source_id) != 64 or any(c not in "0123456789abcdef" for c in source_id):
        raise invalid()
    try:
        record = json.loads((source_root() / f"{source_id}.json").read_text())
    except (OSError, ValueError) as exc:
        raise ApiError(404, "mcp_scan.source_missing", "源码包不存在", "Source bundle does not exist") from exc
    digest = hashlib.sha256(json.dumps(record["files"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if digest != record["sha256"]:
        raise invalid()
    return record
