"""The security event log: sign-ins, refusals, sign-offs and token issues."""

import json
from typing import Any

from backend import clock, db


def record(  # noqa: PLR0913, PLR0917 - one argument per column of the log
    conn: db.Connection,
    tenant_id: str,
    actor: str,
    kind: str,
    target: str,
    outcome: str,
    ip: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """Add one event. Never store a password or a token in the detail."""
    conn.execute(
        "INSERT INTO security_events (tenant_id, actor, kind, target, outcome, ip,"
        " detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            tenant_id,
            actor,
            kind,
            target,
            outcome,
            ip,
            json.dumps(detail or {}),
            clock.stamp(),
        ),
    )


def latest(
    conn: db.Connection, tenant_id: str, limit: int = 200
) -> list[dict[str, Any]]:
    """Return a tenant's latest events, newest first."""
    rows = conn.execute(
        "SELECT * FROM security_events WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
        (tenant_id, limit),
    ).fetchall()
    return [dict(r) | {"detail": json.loads(r["detail"])} for r in rows]
