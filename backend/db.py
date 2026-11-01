"""The SQLite database."""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

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


def path() -> str:
    """Return the database file, from DB_PATH or the repo root."""
    return os.getenv("DB_PATH") or "undercover.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the database, commit on success and close."""
    conn = sqlite3.connect(path(), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def reference(conn: sqlite3.Connection, name: str) -> Any:
    """Return a reference document such as the company settings or the plans."""
    row = conn.execute("SELECT data FROM reference WHERE name = ?", (name,)).fetchone()
    return json.loads(row["data"])


def cents(amount: float) -> int:
    """Convert dollars to integer cents."""
    return round(amount * 100)


def dollars(amount_cents: int) -> float:
    """Convert integer cents to dollars."""
    return amount_cents / 100
