"""The database: SQLite by default, PostgreSQL (Supabase) when DATABASE_URL is set.

Every query is written once, with `?` placeholders, and runs on both through
SQLAlchemy Core. On PostgreSQL all tables live in the `undercover` schema, set as
the search path on each connection, and each process holds at most four
connections, because Supabase's session pooler allows 15 in all.
"""

import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal
from functools import cache
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.pool import NullPool

SCHEMA_NAME = "undercover"
POOL_SIZE = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS reference (name TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handlers (
    handler_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
    can_approve_over_limit INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL, customer_id TEXT NOT NULL,
    data TEXT NOT NULL, state TEXT NOT NULL, state_since TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS calculations (
    id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL, payout_cents INTEGER NOT NULL,
    steps TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL, decision TEXT NOT NULL,
    payout_cents INTEGER NOT NULL, reason TEXT NOT NULL, section TEXT NOT NULL,
    steps TEXT NOT NULL, model TEXT NOT NULL, wording_version TEXT NOT NULL,
    created_at TEXT NOT NULL, sections TEXT NOT NULL, run_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signoffs (
    id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL, handler_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sendbacks (
    id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL, handler_id TEXT NOT NULL,
    reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL, status TEXT NOT NULL,
    error TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
    queue_run_id TEXT NOT NULL, attempt INTEGER NOT NULL, failure TEXT NOT NULL,
    tokens INTEGER NOT NULL, model_calls INTEGER NOT NULL, model TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS queue_runs (
    run_id TEXT PRIMARY KEY, status TEXT NOT NULL, cap INTEGER NOT NULL,
    limits TEXT NOT NULL, model TEXT NOT NULL, reasoning_effort TEXT NOT NULL,
    fingerprint TEXT NOT NULL, todos TEXT NOT NULL, summary TEXT NOT NULL,
    stop_reason TEXT NOT NULL, error TEXT NOT NULL, tokens INTEGER NOT NULL,
    model_calls INTEGER NOT NULL, provider_failures INTEGER NOT NULL,
    started_at TEXT NOT NULL, ended_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS section_reads (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, section_id TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
    name TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signoff_requests (
    id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL, handler_id TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS voice_turns (
    id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, handler_id TEXT NOT NULL,
    transcript TEXT NOT NULL, reply TEXT NOT NULL, speech TEXT NOT NULL,
    ui_action TEXT NOT NULL, tools TEXT NOT NULL, status TEXT NOT NULL,
    latency_ms INTEGER NOT NULL, created_at TEXT NOT NULL);
"""


class Row:
    """A result row like sqlite3.Row: read by name or position, iterated by value.

    dict(row) works through keys().
    """

    def __init__(self, keys: Sequence[str], values: Sequence[Any]) -> None:
        self._keys = list(keys)
        self._values = [plain(v) for v in values]

    def __getitem__(self, key: str | int | slice) -> Any:
        if isinstance(key, int | slice):
            return self._values[key]
        return self._values[self._keys.index(key)]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> list[str]:
        return list(self._keys)


class Result:
    """The rows and row count of one statement."""

    def __init__(self, result: sa.CursorResult[Any]) -> None:
        self.rowcount = result.rowcount
        self._keys = list(result.keys()) if result.returns_rows else []
        self._rows = result.fetchall() if result.returns_rows else []

    def fetchone(self) -> Any:  # noqa: ANN401 - typed like sqlite3, which callers rely on
        return Row(self._keys, self._rows[0]) if self._rows else None

    def fetchall(self) -> list[Row]:
        return [Row(self._keys, r) for r in self._rows]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class Connection:
    """One connection inside one transaction, with the sqlite3 methods we use."""

    def __init__(self, conn: sa.Connection) -> None:
        self.conn = conn
        self.dialect = conn.dialect.name

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Result:
        """Run one statement with `?` placeholders."""
        query, names = statement(sql)
        return Result(self.conn.execute(query, bind(names, params)))

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        """Run one statement for each row of parameters."""
        if rows:
            query, names = statement(sql)
            self.conn.execute(query, [bind(names, r) for r in rows])

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()


def plain(value: Any) -> Any:
    """Return PostgreSQL's numeric sums as the int or float SQLite gives."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


@cache
def statement(sql: str) -> tuple[sa.TextClause, tuple[str, ...]]:
    """Turn `?` placeholders into named ones, escaping any colon in the SQL."""
    parts = sql.replace(":", r"\:").split("?")
    names = tuple(f"p{i}" for i in range(len(parts) - 1))
    text = parts[0] + "".join(f":{n}{p}" for n, p in zip(names, parts[1:], strict=True))
    return sa.text(text), names


def bind(names: tuple[str, ...], params: Sequence[Any]) -> dict[str, Any]:
    """Name the parameters, storing booleans as the integers both databases take."""
    return {
        n: int(v) if isinstance(v, bool) else v
        for n, v in zip(names, params, strict=True)
    }


def ddl(sql: str, dialect: str) -> str:
    """Return a CREATE TABLE for this database: an integer key counts up itself."""
    if dialect == "postgresql":
        return sql.replace(
            "INTEGER PRIMARY KEY", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
        )
    return sql


def path() -> str:
    """Return the SQLite file, from DB_PATH or the repo root."""
    return os.getenv("DB_PATH") or "undercover.db"


def url() -> str:
    """Return the PostgreSQL connection string, or '' to use SQLite."""
    return os.getenv("DATABASE_URL") or ""


def postgres() -> bool:
    """Say whether the backend uses PostgreSQL."""
    return bool(url())


def engine() -> sa.Engine:
    """Return the engine for the database this process uses."""
    return postgres_engine(url()) if postgres() else sqlite_engine(path())


@cache
def sqlite_engine(file: str) -> sa.Engine:
    """Open SQLite in WAL mode, a fresh connection each time, as sqlite3 did."""
    made = sa.create_engine(
        f"sqlite:///{file}",
        connect_args={"timeout": 30, "check_same_thread": False},
        poolclass=NullPool,
    )

    @event.listens_for(made, "connect")
    def setup(dbapi: Any, _record: Any) -> None:
        dbapi.execute("PRAGMA journal_mode=WAL")
        dbapi.execute("PRAGMA busy_timeout=30000")

    return made


@cache
def postgres_engine(conninfo: str) -> sa.Engine:
    """Open PostgreSQL through psycopg, at most POOL_SIZE connections, in our schema."""
    made = sa.create_engine(
        conninfo.replace("postgresql://", "postgresql+psycopg://", 1),
        pool_size=POOL_SIZE,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=300,
    )

    @event.listens_for(made, "connect")
    def setup(dbapi: Any, _record: Any) -> None:
        with dbapi.cursor() as cursor:
            cursor.execute(f"SET search_path TO {SCHEMA_NAME}")
        dbapi.commit()

    return made


@contextmanager
def connect() -> Iterator[Connection]:
    """Open a connection, commit on success, roll back on error, and give it back.

    Keep each connection short: open it for one step, never across a model call.
    """
    with engine().connect() as conn:
        wrapped = Connection(conn)
        try:
            yield wrapped
        except BaseException:
            conn.rollback()
            raise
        conn.commit()


def reference(conn: Connection, name: str, tenant_id: str) -> Any:
    """Return a tenant's reference document, such as its company settings.

    A tenant's own copy wins; without one it gets the shared document.
    """
    row = (
        conn.execute(
            "SELECT data FROM tenant_reference WHERE tenant_id = ? AND name = ?",
            (tenant_id, name),
        ).fetchone()
        or conn.execute("SELECT data FROM reference WHERE name = ?", (name,)).fetchone()
    )
    if row is None:
        raise KeyError(name)
    return json.loads(row["data"])


def cents(amount: float) -> int:
    """Convert dollars to integer cents."""
    return round(amount * 100)


def dollars(amount_cents: int) -> float:
    """Convert integer cents to dollars."""
    return amount_cents / 100
