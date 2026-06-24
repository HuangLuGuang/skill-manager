"""Text decoding helpers for user-provided skill files."""

from __future__ import annotations

from pathlib import Path


TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5", "cp1252", "latin-1")


def read_text_fallback(path: str | Path) -> tuple[str, str]:
    data = Path(path).read_bytes()
    last_error: UnicodeDecodeError | None = None
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return "", "utf-8"
