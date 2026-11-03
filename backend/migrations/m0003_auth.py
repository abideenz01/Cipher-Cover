"""Accounts, sessions, agent service tokens and the security event log.

Session and service tokens are stored only as SHA-256 hashes, and passwords
only as scrypt hashes.
"""

import sqlite3

VERSION = 3
NAME = "auth"

SCHEMA = """
CREATE TABLE users (
    user_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, handler_id TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE user_roles (
    user_id TEXT NOT NULL, role TEXT NOT NULL, PRIMARY KEY (user_id, role));
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
    csrf_hash TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL,
    expires_at TEXT NOT NULL, revoked_at TEXT NOT NULL);
CREATE TABLE service_tokens (
    token_hash TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, kind TEXT NOT NULL,
    user_id TEXT NOT NULL, run_id TEXT NOT NULL, claim_id TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT NOT NULL);
CREATE TABLE security_events (
    id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, actor TEXT NOT NULL,
    kind TEXT NOT NULL, target TEXT NOT NULL, outcome TEXT NOT NULL,
    ip TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX users_tenant ON users (tenant_id);
CREATE INDEX service_tokens_run ON service_tokens (run_id);
CREATE INDEX security_events_tenant ON security_events (tenant_id);
"""


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the account, session, token and event tables."""
    for statement in SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
