"""Opt-in synthetic benchmark diagnostics; never records SQL values or bodies."""
import contextvars
from contextlib import asynccontextmanager
import functools
import inspect
import json
import sys
import threading
import time


def install(directory):
    import anyio.to_thread
    import httpx
    from sqlalchemy import event

    from backend.routers import aidr, llm_gateway, mcp_gateway
    from backend import aidr_skill_usage, main
    from backend.services import gateway_db
    from backend.sqlite_db import engine

    label = contextvars.ContextVar('benchmark_phase', default='background')
    lock = threading.Lock()
    output = (directory / 'diagnostics.jsonl').open('a', buffering=1)

    def emit(kind, **fields):
        with lock:
            output.write(json.dumps(dict(at=time.time(), kind=kind, phase=label.get(), **fields)) + '\n')

    # Capture all shared worker admissions, including sync page routes and
    # Skill maintenance, rather than only gateway_db's wrapper.
    original_thread = anyio.to_thread.run_sync
    async def thread(function, *args, **kwargs):
        queued = time.perf_counter()
        def worker():
            started = time.perf_counter()
            cpu = time.thread_time()
            try:
                return function(*args)
            finally:
                emit('thread_worker', queue_ms=(started-queued)*1000,
                     operation=getattr(getattr(function, 'func', function), '__qualname__', 'callable'),
                     work_ms=(time.perf_counter()-started)*1000, cpu_ms=(time.thread_time()-cpu)*1000)
        return await original_thread(worker, **kwargs)
    anyio.to_thread.run_sync = thread

    @main.app.middleware('http')
    async def page_phase(request, call_next):
        name = 'skill_list' if request.url.path.endswith('/skill-uses') else 'dashboard' if request.url.path.endswith('/dashboard/overview') else 'request'
        token = label.set(name)
        try:
            return await call_next(request)
        finally:
            label.reset(token)

    original_maintenance = aidr_skill_usage.maintenance
    def maintenance():
        token = label.set('skill_audit')
        try:
            return original_maintenance()
        finally:
            label.reset(token)
    aidr_skill_usage.maintenance = maintenance

    # Distinguish each production cleanup loop without changing its budget or
    # scheduling. This wrapper is installed only for instrumented experiments.
    from backend import aidr_retention
    original_retention = main.retention_loop

    async def retention(cleanup, name, **kwargs):
        def measured():
            token = label.set('cleanup:' + name)
            try:
                return cleanup()
            finally:
                label.reset(token)

        async def measured_async():
            token = label.set('cleanup:' + name)
            try:
                return await cleanup()
            finally:
                label.reset(token)

        await original_retention(measured_async if inspect.iscoroutinefunction(cleanup) else measured, name, **kwargs)

    main.retention_loop = retention
    aidr_retention.run_retention_loop = retention

    original_db = gateway_db.run_db
    async def run_db(db, function, *args, **kwargs):
        token = label.set(function.__qualname__)
        started = time.perf_counter()
        try:
            return await original_db(db, function, *args, **kwargs)
        finally:
            emit('phase', ms=(time.perf_counter() - started) * 1000)
            label.reset(token)

    original_pool = gateway_db.run_in_threadpool
    async def pool(function, *args, **kwargs):
        queued = time.perf_counter()
        def worker():
            target = getattr(function, 'func', function)
            operation = getattr(target, '__qualname__', type(target).__name__)
            token = label.set(f'{getattr(target, "__module__", "")}.{operation}') if label.get() == 'background' else None
            started = time.perf_counter()
            cpu = time.thread_time()
            try:
                return function(*args, **kwargs)
            finally:
                emit('worker', queue_ms=(started - queued) * 1000,
                     operation=getattr(getattr(function, 'func', function), '__qualname__', 'callable'),
                     work_ms=(time.perf_counter() - started) * 1000, cpu_ms=(time.thread_time()-cpu)*1000)
                if token is not None:
                    label.reset(token)
        return await original_pool(worker)
    gateway_db.run_in_threadpool = pool
    modules = [gateway_db, aidr, llm_gateway, mcp_gateway]
    if 'backend.services.aidr_ingest' in sys.modules:
        modules.append(sys.modules['backend.services.aidr_ingest'])
    for module in modules:
        module.run_db = run_db

    if 'backend.services.aidr_ingest' in sys.modules:
        ingest = sys.modules['backend.services.aidr_ingest']
        if hasattr(ingest, 'admission'):
            original_admission = ingest.admission
            active_bulk = 0
            def measured_admission(operation):
                @asynccontextmanager
                async def admitted():
                    nonlocal active_bulk
                    started = time.perf_counter()
                    async with original_admission():
                        active_bulk += 1
                        try:
                            emit('bulk_admission', operation=operation, ms=(time.perf_counter()-started)*1000,
                                 borrowed=active_bulk)
                            yield
                        finally:
                            active_bulk -= 1
                return admitted
            ingest.admission = measured_admission('ingestion')
            aidr_skill_usage.admission = measured_admission('skill_audit')
            for module_name, operation in [('backend.aidr_overview', 'overview_projection'),
                                           ('backend.aidr_retention', 'aidr_retention')]:
                module = sys.modules.get(module_name)
                if module is not None and hasattr(module, 'admission'):
                    module.admission = measured_admission(operation)
        original_ingest = ingest.run_ingest
        async def admission(db, function, *args, **kwargs):
            started = time.perf_counter()
            try:
                return await original_ingest(db, function, *args, **kwargs)
            finally:
                emit('ingestion_total', operation=function.__qualname__, ms=(time.perf_counter()-started)*1000)
        aidr.run_ingest = admission
    original_get = engine.pool._do_get
    def get_connection():
        started = time.perf_counter()
        try:
            return original_get()
        finally:
            emit('connection_pool', ms=(time.perf_counter() - started) * 1000)
    engine.pool._do_get = get_connection

    original_commit = engine.dialect.do_commit
    writers = {}
    def writer_key(connection):
        return id(getattr(connection, 'driver_connection', connection))

    def acquired(conn):
        writers[writer_key(conn.connection)] = dict(started=time.perf_counter(), owner=label.get())

    def released(connection):
        previous = writers.pop(writer_key(connection), None)
        if previous is not None:
            emit('writer_hold', owner=previous['owner'], ms=(time.perf_counter()-previous['started'])*1000)

    def commit(connection):
        started = time.perf_counter()
        try:
            result = original_commit(connection)
            released(connection)
            return result
        finally:
            emit('commit', ms=(time.perf_counter() - started) * 1000)
    engine.dialect.do_commit = commit

    original_rollback = engine.dialect.do_rollback
    def rollback(connection):
        result = original_rollback(connection)
        released(connection)
        return result
    engine.dialect.do_rollback = rollback

    @event.listens_for(engine, 'before_cursor_execute')
    def before(conn, cursor, statement, parameters, context, executemany):
        # Diagnostic runs only: make the implicit acquisition immediately before
        # the first DML explicit, so busy-handler time is separated from row work.
        # Formal comparisons run without this probe.
        verb = statement.lstrip().split(None, 1)[0].upper()
        raw = conn.connection.driver_connection
        context.benchmark_initial_writers = sorted({item['owner'] for item in list(writers.values())})
        if verb in {'INSERT', 'UPDATE', 'DELETE'} and not raw.in_transaction:
            started = time.perf_counter()
            raw.execute('BEGIN IMMEDIATE').close()
            emit('writer_acquire', ms=(time.perf_counter() - started) * 1000,
                 initial_writers=context.benchmark_initial_writers)
            acquired(conn)
            conn.info['benchmark_writer_started'] = time.perf_counter()
            conn.info['benchmark_writer_sql'] = {}
        context.benchmark_cpu = time.thread_time()
        context.benchmark_started = time.perf_counter()

    @event.listens_for(engine, 'after_cursor_execute')
    def after(conn, cursor, statement, parameters, context, executemany):
        ms = (time.perf_counter() - context.benchmark_started) * 1000
        if statement.strip().upper().startswith('BEGIN IMMEDIATE'):
            emit('writer_acquire', ms=ms, initial_writers=context.benchmark_initial_writers)
            acquired(conn)
            conn.info['benchmark_writer_started'] = time.perf_counter()
            conn.info['benchmark_writer_sql'] = {}
        if 'benchmark_writer_started' in conn.info:
            counts = conn.info.setdefault('benchmark_writer_sql', {})
            verb = statement.lstrip().split(None, 1)[0].upper()
            counts[verb] = counts.get(verb, 0) + 1
        if ms >= 5:
            # SQL verb/table only; no arbitrary SQL text or parameters.
            words = statement.split()
            verb = words[0].upper()
            table = words[2] if verb in {'INSERT', 'DELETE'} else words[1] if verb == 'UPDATE' else ''
            emit('sql', verb=verb, table=table, ms=ms,
                 cpu_ms=(time.thread_time() - context.benchmark_cpu) * 1000)

    def end_write(conn):
        started = conn.info.pop('benchmark_writer_started', None)
        if started is not None:
            emit('write_transaction', ms=(time.perf_counter()-started)*1000,
                 sql_counts=conn.info.pop('benchmark_writer_sql', {}))
    event.listen(engine, 'commit', end_write)
    event.listen(engine, 'rollback', end_write)

    original_transport = httpx.AsyncHTTPTransport.handle_async_request
    @functools.wraps(original_transport)
    async def transport(self, request):
        started = time.perf_counter()
        try:
            return await original_transport(self, request)
        except Exception as exc:
            seen = set()
            def causes(error):
                if id(error) in seen:
                    return []
                seen.add(id(error))
                result = [dict(type=type(error).__name__, errno=getattr(error, 'errno', None))]
                if error.__cause__:
                    result.extend(causes(error.__cause__))
                if error.__context__:
                    result.extend(causes(error.__context__))
                for child in getattr(error, 'exceptions', ()):
                    result.extend(causes(child))
                return result
            emit('transport_error', causes=causes(exc))
            raise
        finally:
            emit('transport', ms=(time.perf_counter() - started) * 1000)
    httpx.AsyncHTTPTransport.handle_async_request = transport
