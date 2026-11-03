"""One SQLAlchemy engine for the process (connection pool, UTC, statement timeout) and helpers for transactions."""
import threading
from contextlib import contextmanager

import sqlalchemy as sa

from . import settings

_engines: dict = {}
_lock = threading.Lock()


def engine(role: str = "app") -> sa.Engine:
    key = (role, settings.url(role))
    with _lock:
        if key not in _engines:
            _engines[key] = sa.create_engine(
                key[1], pool_size=8, max_overflow=8, pool_pre_ping=True, pool_recycle=1800,
                connect_args={"options": "-c timezone=UTC -c statement_timeout=60000 -c idle_in_transaction_session_timeout=120000 "
                                         "-c application_name=envirosense"})
        return _engines[key]


@contextmanager
def tx(role: str = "app"):
    """A transaction: commits on success, rolls back on any exception."""
    with engine(role).begin() as c:
        yield c


def one(c, sql: str, /, **p):
    r = c.execute(sa.text(sql), p).mappings().first()
    return dict(r) if r else None


def rows(c, sql: str, **p) -> list:
    return [dict(r) for r in c.execute(sa.text(sql), p).mappings()]


def run(c, sql: str, /, **p):
    return c.execute(sa.text(sql), p)


def dispose():
    with _lock:
        for e in _engines.values():
            e.dispose()
        _engines.clear()


@contextmanager
def using(c=None, role: str = "app"):
    """Use the given connection (so a change joins the caller's transaction), or open a transaction of its own."""
    if c is not None:
        yield c
    else:
        with tx(role) as conn:
            yield conn
