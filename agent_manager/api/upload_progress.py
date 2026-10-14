"""Stream upload preparation progress from blocking ZIP processing."""

import asyncio
import json
import time

import anyio
from fastapi.responses import StreamingResponse
from agent_manager.api.import_work import run_import_work


def stream_upload_progress(work, initial_stage="extracting"):
    async def events():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        active = True
        last_stage = None
        last_sent = 0.0

        def emit(event):
            if active:
                loop.call_soon_threadsafe(queue.put_nowait, event)

        def progress(stage, completed, total):
            nonlocal last_stage, last_sent
            now = time.monotonic()
            if stage != last_stage or completed == total or now - last_sent >= 0.1:
                emit({"type": "progress", "stage": stage, "completed": completed, "total": total})
                last_stage, last_sent = stage, now

        def run():
            try:
                result = work(progress)
                emit({"type": "result", "data": result.model_dump(mode="json")})
            except Exception:
                emit({"type": "error", "error_code": "upload.parse_failed"})

        task = asyncio.create_task(run_import_work(run))
        try:
            yield json.dumps({"type": "progress", "stage": initial_stage, "completed": 0, "total": 0}) + "\n"
            while True:
                event = await queue.get()
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["type"] != "progress":
                    break
        finally:
            active = False
            # The thread finishes its filesystem cleanup even if the client disconnects.
            with anyio.CancelScope(shield=True):
                await asyncio.shield(task)

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
