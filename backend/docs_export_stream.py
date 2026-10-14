"""Stream PDF generation progress and the resulting file without retaining export jobs."""

import asyncio
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from .docs_export_pdf import build_docs_export_pdf


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="docs-pdf")


async def stream_docs_export(payload, *, generated_at: str):
    events = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stopped = Event()

    def emit(data):
        if stopped.is_set():
            raise InterruptedError("PDF export disconnected")
        loop.call_soon_threadsafe(events.put_nowait, data)

    def progress(data):
        emit({"type": "progress", **data})

    def generate():
        try:
            document = build_docs_export_pdf(payload, generated_at=generated_at, progress=progress)
            for offset in range(0, len(document), 64 * 1024):
                if stopped.is_set():
                    return
                emit({
                    "type": "chunk",
                    "data": base64.b64encode(document[offset:offset + 64 * 1024]).decode("ascii"),
                })
            emit({"type": "complete"})
        except InterruptedError:
            return
        except Exception:
            if not stopped.is_set():
                emit({"type": "error", "error_code": "docs_export.generation_failed"})

    future = _executor.submit(generate)
    try:
        yield json.dumps({"type": "progress", "stage": "queued"}) + "\n"
        while True:
            try:
                event = await asyncio.wait_for(events.get(), timeout=10)
            except asyncio.TimeoutError:
                yield "\n"
                continue
            yield json.dumps(event, ensure_ascii=False) + "\n"
            if event["type"] in {"complete", "error"}:
                return
    finally:
        stopped.set()
        future.cancel()
