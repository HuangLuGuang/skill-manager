"""Bounded ZIP extraction and disposable security-analysis copies."""
import os
import shutil
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

import psutil
from fastapi import HTTPException


def safe_extract_zip(zip_path: Path, extract_dir: Path, *, skipped_symlinks: list[str] | None = None, archive_prefix: str = "", progress=None, budget=None) -> None:
    extract_root = extract_dir.resolve()
    budget = budget if budget is not None else {"files": 0, "bytes": 0}
    with zipfile.ZipFile(zip_path) as zf:
        entries = zf.infolist()
        for index, info in enumerate(entries):
            if progress:
                progress("extracting", index, len(entries))
            name = info.filename
            if ".." in name or name.startswith("/"):
                raise HTTPException(status_code=400, detail=f"Unsafe path in ZIP: {name}")
            if not info.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("utf-8")
                except UnicodeError:
                    pass
            if stat.S_ISLNK(info.external_attr >> 16):
                if skipped_symlinks is not None:
                    skipped_symlinks.append(f"{archive_prefix}{name}")
                    continue
                raise HTTPException(status_code=400, detail=f"Symlinks are not allowed in ZIP: {name}")
            if not info.is_dir():
                budget["files"] += 1
                budget["bytes"] += info.file_size
                if budget["files"] > 50000 or budget["bytes"] > 1024 ** 3 or info.file_size > 100 * 1024 ** 2:
                    raise HTTPException(status_code=413, detail="Archive extraction limits exceeded")
            target = (extract_root / name).resolve()
            try:
                target.relative_to(extract_root)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Unsafe path in ZIP: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        if progress:
            progress("extracting", len(entries), len(entries))


def cleanup_abandoned_analysis():
    for directory in Path(tempfile.gettempdir()).glob("agent-manager-analysis-*-*"):
        try:
            pid = int(directory.name.split("-")[3])
            if pid > 0 and not psutil.pid_exists(pid) and directory.is_dir() and not directory.is_symlink():
                shutil.rmtree(directory, ignore_errors=True)
        except (ValueError, OSError, psutil.AccessDenied):
            continue


@contextmanager
def analysis_directory(skill_path: Path):
    cleanup_abandoned_analysis()
    archives = sorted(path for path in skill_path.rglob("*") if path.is_file() and path.suffix.lower() == ".zip")
    if not archives:
        yield skill_path
        return
    with tempfile.TemporaryDirectory(prefix=f"agent-manager-analysis-{os.getpid()}-") as temporary:
        root = Path(temporary) / "skill"
        shutil.copytree(skill_path, root)
        budget = {"files": 0, "bytes": 0}
        queue = [(root / path.relative_to(skill_path), 0) for path in archives]
        while queue:
            archive, depth = queue.pop(0)
            if not zipfile.is_zipfile(archive):
                continue
            if depth >= 8:
                raise HTTPException(status_code=413, detail="Archive extraction limits exceeded")
            # A separate sibling avoids overwriting original files with ZIP members.
            target = archive.with_name(archive.name + ".contents")
            while target.exists():
                target = target.with_name(target.name + ".contents")
            target.mkdir()
            safe_extract_zip(archive, target, budget=budget)
            queue.extend((path, depth + 1) for path in sorted(target.rglob("*"))
                         if path.is_file() and path.suffix.lower() == ".zip")
        yield root
