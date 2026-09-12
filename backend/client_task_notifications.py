"""Wake task waiters after commits, with one cross-process catch-up query per hub."""
import asyncio
import threading
from contextlib import asynccontextmanager

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from .models import ClientTask

_hubs = {}
_lock = threading.Lock()


class TaskHub:
    def __init__(self, engine, loop):
        self.engine, self.loop = engine, loop
        self.waiters = {}
        self.monitor = None
        self.initial = loop.create_task(asyncio.to_thread(self.latest_id))

    def latest_id(self):
        with self.engine.connect() as connection:
            return connection.scalar(select(func.max(ClientTask.id))) or 0

    def notify(self, clients=None):
        for client, waiters in list(self.waiters.items()):
            if clients is None or client in clients:
                for waiter in list(waiters):
                    waiter.set()

    def newer(self, cursor):
        with self.engine.connect() as connection:
            return connection.execute(select(ClientTask.id, ClientTask.client_id)
                                      .where(ClientTask.id > cursor).order_by(ClientTask.id).limit(1000)).all()

    async def watch(self):
        cursor = await self.initial
        while self.waiters:
            await asyncio.sleep(1)
            try:
                rows = await asyncio.to_thread(self.newer, cursor)
                if rows:
                    cursor = rows[-1][0]
                    self.notify({row[1] for row in rows})
            except Exception:
                # A later request revalidates the database and authorization.
                self.notify()

    @asynccontextmanager
    async def subscribe(self, client_id):
        await self.initial
        waiter = asyncio.Event()
        self.waiters.setdefault(client_id, set()).add(waiter)
        if self.monitor is None or self.monitor.done():
            self.monitor = self.loop.create_task(self.watch())
        try:
            yield waiter
        finally:
            self.waiters[client_id].discard(waiter)
            if not self.waiters[client_id]:
                del self.waiters[client_id]
            if not self.waiters:
                self.monitor.cancel()
                with _lock:
                    _hubs.pop((self.engine, self.loop), None)


def task_hub(engine):
    loop = asyncio.get_running_loop()
    with _lock:
        key = (engine, loop)
        if key not in _hubs:
            _hubs[key] = TaskHub(engine, loop)
        return _hubs[key]


@event.listens_for(Session, "after_flush")
def remember_tasks(session, _context):
    clients = {row.client_id for row in session.new if isinstance(row, ClientTask)}
    if clients:
        session.info.setdefault("client_task_notifications", set()).update(clients)


@event.listens_for(Session, "do_orm_execute")
def remember_insert(state):
    if state.is_insert and getattr(getattr(state.statement, "table", None), "name", None) == "client_tasks":
        client_id = state.statement.compile().params.get("client_id")
        session_clients = state.session.info.setdefault("client_task_notifications", set())
        session_clients.add(client_id)


@event.listens_for(Session, "after_commit")
def notify_committed(session):
    clients = session.info.pop("client_task_notifications", set())
    if not clients:
        return
    engine = session.get_bind()
    with _lock:
        hubs = [hub for (bound, loop), hub in _hubs.items() if bound is engine and not loop.is_closed()]
    for hub in hubs:
        hub.loop.call_soon_threadsafe(hub.notify, None if None in clients else clients)


@event.listens_for(Session, "after_rollback")
def discard_rollback(session):
    session.info.pop("client_task_notifications", None)
